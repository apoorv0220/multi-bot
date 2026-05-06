import asyncio
import os
import json
import uuid
import asyncio
import time
from datetime import datetime
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import openai
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.models import Distance, VectorParams
import logging
from fuzzy_matcher import FuzzyMatcher
from typing import Optional, Dict, Any, List
from url_utils import validate_and_fix_url, get_base_url

from embedder import Embedder
from wordpress_fetcher import WordPressFetcher
from database import ChatDatabase # Import the new ChatDatabase class

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app.log")
    ]
)
logger = logging.getLogger("mrnwebdesigns-chatbot")

# Local imports - use relative imports
from scraper import WebScraper

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI(title="MRN Web Designs AI Chatbot API",
              description="API for AI-powered search across MRN Web Designs content")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger.info("Initializing services...")

# Initialize OpenAI client
openai.api_key = os.getenv("OPENAI_API_KEY")
logger.info(f"OpenAI API key configured: {openai.api_key[:5]}...{openai.api_key[-4:] if openai.api_key else 'NOT_SET'}")

# Try to import Qdrant and related modules, but do not crash if unavailable
qdrant_client = None

def _initialize_qdrant_client_with_retries(max_retries: int = 10, retry_delay: float = 2.0):
    """
    Initialize Qdrant client with retry logic.

    Important: if this fails once at import-time, Gunicorn workers can get stuck in a state
    where `qdrant_client` is None for the lifetime of that worker.
    """
    # Define Qdrant connection parameters from environment or use defaults
    QDRANT_HOST = os.getenv("QDRANT_HOST", "mrnwebdesigns-qdrant")
    QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
    COLLECTION_NAME = os.getenv("COLLECTION_NAME", "mrnwebdesigns_content")

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Connecting to Qdrant at {QDRANT_HOST}:{QDRANT_PORT} (attempt {attempt}/{max_retries})")
            client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

            # Ensure Qdrant is responding
            collections = client.get_collections().collections
            collection_names = [collection.name for collection in collections]

            # Check if collection exists, create if not
            if COLLECTION_NAME not in collection_names:
                logger.info(f"Creating collection '{COLLECTION_NAME}'...")
                client.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=VectorParams(
                        size=1536,  # Dimension for text-embedding-3-small
                        distance=Distance.COSINE
                    )
                )
                client.create_payload_index(
                    collection_name=COLLECTION_NAME,
                    field_name="source_type",
                    field_schema=models.PayloadSchemaType.KEYWORD
                )
                logger.info(f"Collection '{COLLECTION_NAME}' created")

            return client
        except Exception as e:
            last_error = e
            logger.warning(f"Failed to connect to Qdrant (attempt {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                time.sleep(retry_delay)

    raise last_error

try:
    qdrant_client = _initialize_qdrant_client_with_retries()
except Exception as e:
    logger.error(f"Qdrant unavailable or error initializing: {e}")
    qdrant_client = None

# Share the client with the embedder module
import embedder as embedder_module
embedder_module.qdrant_client = qdrant_client

# Initialize fuzzy matcher
fuzzy_matcher = FuzzyMatcher()

# Initialize database
db = ChatDatabase()

# Initialize scraper
scraper = WebScraper()

# Define request models
class QueryRequest(BaseModel):
    query: str
    max_results: int = 5

# Define response models
class SearchResult(BaseModel):
    content: str
    source: str
    url: str
    score: float

class QueryResponse(BaseModel):
    answer: str
    sources: list[SearchResult] = []

class ChatRequest(BaseModel):
    message: str
    max_results: int = 3
    session_id: str | None = None  # Add session_id to ChatRequest

class ChatResponse(BaseModel):
    response: str
    source: str 
    confidence: float
    sources: List[SearchResult] | None = None # Full sources data
    session_id: str | None = None
    source_details: dict | None = None # New field for structured source data


class SaveHistoryRequest(BaseModel):
    session_id: str
    event_type: str
    user_message_text: str | None = None
    bot_response_text: str | None = None
    bot_response_source: dict | None = None
    bot_response_confidence: float | None = None
    trigger_detection_method: str | None = None
    trigger_confidence: float | None = None
    trigger_matched_phrase: str | None = None


class StartSessionRequest(BaseModel):
    session_id: str | None = None

# Helper function to generate embeddings
async def generate_embedding(text: str) -> List[float]:
    try:
        response = openai.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"Error generating embedding: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate embedding")

# Helper function to search in Qdrant
async def search_qdrant(embedding: List[float], limit: int = 5) -> List[Any]:
    if qdrant_client is None:
        raise HTTPException(status_code=503, detail="Qdrant service is unavailable")
    
    collection_name = os.getenv("COLLECTION_NAME", "mrnwebdesigns_content")

    try:
        # First try to search in MRN Web Designs content (prioritized)
        mrnwebdesigns_results = qdrant_client.search(
            collection_name=collection_name,
            query_vector=embedding,
            limit=limit,
            score_threshold=0.6,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="source_type",
                        match=models.MatchValue(value="mrnwebdesigns_ie")
                    )
                ]
            )
        )
        
        logger.info(f"Found {len(mrnwebdesigns_results)} mrnwebdesigns.com results")
        
        # If we don't have enough results from MRN Web Designs, search external sources
        if len(mrnwebdesigns_results) < limit or max([r.score for r in mrnwebdesigns_results] + [0]) < 0.7:
            external_results = qdrant_client.search(
                collection_name=collection_name,
                query_vector=embedding,
                query_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="source_type",
                            match=models.MatchValue(value="external")
                        )
                    ]
                ),
                limit=limit
            )
            
            # Combine and sort results
            all_results = mrnwebdesigns_results + external_results
            all_results.sort(key=lambda x: x.score, reverse=True)
            logger.info(f"Added {len(external_results)} external results, total: {len(all_results)}")
            return all_results[:limit]
        
        return mrnwebdesigns_results
    except Exception as e:
        logger.error(f"Error searching Qdrant: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to search knowledge base: {e}")

# Helper function to truncate text for context
def truncate_text_for_context(text, max_chars=3000):
    """Truncate text to fit within context window, preserving beginning and end"""
    if len(text) <= max_chars:
        return text
    
    # Take 80% from beginning, 20% from end
    begin_portion = int(max_chars * 0.8)
    end_portion = max_chars - begin_portion
    return text[:begin_portion] + "\n...[content truncated]...\n" + text[-end_portion:]

# Helper function to preprocess and enhance query using OpenAI
async def preprocess_query(original_query: str) -> str:
    """
    Use OpenAI to normalize and enhance queries for better search results.
    Converts questions like "your office address" to "MRN Web Designs office address".
    """
    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system", 
                    "content": """You are a query preprocessor for MRN Web Designs chatbot. Your job is to normalize and enhance user queries to make them more searchable in a knowledge base.

Rules:
1. Replace pronouns like "your", "you", "yours" with "MRN Web Designs"
2. Add relevant keywords that would help find information
3. Expand abbreviations and make queries more specific
4. Keep the original intent and meaning
5. Output only the enhanced query, nothing else

Examples:
- "your office address" → "MRN Web Designs office address location contact information"
- "what services do you offer" → "MRN Web Designs services web design development SEO digital marketing"
- "your pricing" → "MRN Web Designs pricing cost website development packages"
- "do you work with small businesses" → "MRN Web Designs small business services web design"
- "your experience" → "MRN Web Designs experience portfolio company background"
- "how can you help me" → "MRN Web Designs services help assistance web design digital marketing"
- "your phone number" → "MRN Web Designs phone number contact telephone call"
- "what is your contact number" → "MRN Web Designs contact phone number telephone"
- "how to reach you" → "MRN Web Designs contact phone address reach"
"""
                },
                {
                    "role": "user", 
                    "content": f"Original query: {original_query}"
                }
            ],
            max_tokens=100,
            temperature=0.1  # Low temperature for consistent results
        )
        
        enhanced_query = response.choices[0].message.content.strip()
        logger.info(f"Query enhanced: '{original_query}' → '{enhanced_query}'")
        return enhanced_query
        
    except Exception as e:
        logger.warning(f"Query preprocessing failed: {e}. Using original query.")
        return original_query

# Helper function to generate AI answer
async def generate_answer(query: str, context_texts: List[str]) -> str:
    try:
        # Set a maximum total context length (in chars) to prevent errors
        max_total_context = 14000  # Safe limit for gpt-3.5-turbo (16k tokens)
        
        # Truncate each context text
        truncated_texts = []
        total_chars = 0
        max_chars_per_source = max_total_context // max(len(context_texts), 1)
        
        for text in context_texts:
            # Limit each source text proportionally
            truncated = truncate_text_for_context(text, max_chars_per_source)
            truncated_texts.append(truncated)
            total_chars += len(truncated)
        
        # If still too large, reduce even more
        if total_chars > max_total_context:
            # Calculate reduction factor
            reduction_factor = max_total_context / total_chars
            
            truncated_texts = []
            for text in context_texts:
                # Adjust max chars based on reduction factor
                adjusted_max = int(max_chars_per_source * reduction_factor)
                truncated = truncate_text_for_context(text, max(adjusted_max, 500))
                truncated_texts.append(truncated)
        
        # Join the truncated texts
        context = "\n\n---\n\n".join(truncated_texts)
        logger.info(f"Total context length (chars): {len(context)}")
        
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant specialized in web design and digital marketing. Your role is to format information found in the context to provide accurate, helpful, and professional information about website design, development, maintenance, SEO, paid search, and social media marketing. Present this information as if it's directly from MRN Web Designs, a custom web design and digital marketing agency. Focus on helping businesses stand out from the competition by creating digital experiences that boost visibility and drive engagement. Always emphasize custom solutions over templates or cookie-cutter approaches. IMPORTANT: Keep your responses concise and under 250 characters to ensure clarity and readability."},
                {"role": "user", "content": f"Question: {query}\n\nContext: {context}"}
            ]
        )
        
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error generating answer: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate answer")

# Helper function to normalize text for keyword matching
def normalize_text_for_keywords(text: str) -> str:
    """Normalize text by lowercasing, removing punctuation, and extra spaces."""
    import re
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s]', '', text) # Remove punctuation
    text = re.sub(r'\s+', ' ', text).strip() # Replace multiple spaces with single space
    return text

# API endpoint for the chat query
@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> Dict[str, Any]:
    """
    Handle chat requests with fuzzy matching for common queries.
    Falls back to vector search if no fuzzy match is found.
    """
    global qdrant_client
    try:
        # Get or create session
        session_data = db.get_or_create_session(request.session_id)
        if not session_data:
            raise HTTPException(status_code=500, detail="Could not create or retrieve session")
        internal_session_id = session_data['id']
        current_session_uuid = session_data['session_id']

        # Try fuzzy matching first
        fuzzy_response = fuzzy_matcher.get_response(request.message)
        if fuzzy_response:
            logger.info(f"Fuzzy match found for query: {request.message}")
            return {
                "response": fuzzy_response["response"],
                "source": fuzzy_response["source"],
                "confidence": fuzzy_response["confidence"],
                "sources": fuzzy_response["sources"]
            }
            db.save_chat_event(event_data)
            logger.debug(f"Event data sent to db.save_chat_event (fuzzy_match): {event_data}") # Debug log
            return ChatResponse(
                response=fuzzy_response,
                source="fuzzy_match", # Simple string
                confidence=1.0,
                sources=[],
                session_id=current_session_uuid,
                source_details={"type": "fuzzy_match"} # Structured data
            )
        
        # If Qdrant is not available, return a default message
        if qdrant_client is None:
            logger.warning("Qdrant is not available, cannot perform vector search yet. Attempting reconnect...")
            try:
                qdrant_client = _initialize_qdrant_client_with_retries(max_retries=10, retry_delay=1.0)
                embedder_module.qdrant_client = qdrant_client
            except Exception as e:
                logger.warning(f"Reconnect attempt failed: {e}")
                return {
                    "response": "Sorry, our knowledge base is temporarily unavailable. Please try again later or ask a basic question.",
                    "source": "unavailable",
                    "confidence": 0.0,
                    "sources": []
                }

        # Preprocess and enhance the query for better search results
        enhanced_query = await preprocess_query(request.message)
        
        # Generate embedding for the enhanced query
        embedding = await generate_embedding(enhanced_query)
        
        # Search in Qdrant
        raw_search_results = await search_qdrant(embedding, request.max_results)
        
        # --- Start of new minimalist solution: Keyword-Based Reranking/Boosting ---
        # Normalize the query for keyword matching
        normalized_query_words = set(normalize_text_for_keywords(request.message).split())
        
        # Create a mutable list of results to allow reordering
        reordered_results = []
        
        # Separate exact matches and other results
        exact_match_results = []
        other_results = []

        for result in raw_search_results:
            title = result.payload.get('title', '')
            url = result.payload.get('url', '')
            content_preview = result.payload.get('content', '')

            normalized_title = normalize_text_for_keywords(title)
            normalized_url_path = normalize_text_for_keywords(url.split('/')[-1].replace('-', ' ')) # Get last part of URL and replace hyphens
            normalized_content = normalize_text_for_keywords(content_preview)
            
            # Check for strong keyword overlap in title or URL for boosting
            # This logic needs careful tuning to avoid over-boosting irrelevant results
            title_keywords = set(normalized_title.split())
            url_keywords = set(normalized_url_path.split())
            content_keywords = set(normalized_content.split())
            
            # Simple overlap check: at least 2 common words, or a significant portion of query words in title/url
            common_words_in_title = len(normalized_query_words.intersection(title_keywords))
            common_words_in_url = len(normalized_query_words.intersection(url_keywords))
            common_words_in_content = len(normalized_query_words.intersection(content_keywords))

            # A simple rule: if a significant portion of query words (e.g., >= 50%) are in the title or URL, consider it a strong match.
            # Or if it's a direct phrase match in the title
            is_strong_title_match = (common_words_in_title >= len(normalized_query_words) * 0.5) or (normalize_text_for_keywords(request.message) in normalized_title)
            is_strong_url_match = (common_words_in_url >= len(normalized_query_words) * 0.5) or (normalize_text_for_keywords(request.message) in normalized_url_path)
            
            # Prioritize results where title or URL path strongly match the query
            if is_strong_title_match or is_strong_url_match:
                # Assign a very high temporary score to ensure it's at the top, or use a separate list
                exact_match_results.append(result)
            else:
                other_results.append(result)

        # Sort exact matches (if any) by their original Qdrant score (highest first)
        exact_match_results.sort(key=lambda x: x.score, reverse=True)
        # Sort other results by their original Qdrant score
        other_results.sort(key=lambda x: x.score, reverse=True)
        
        # Combine: exact matches first, then other results
        search_results_with_rerank = exact_match_results + other_results
        
        # If there are more results than max_results, truncate
        search_results = search_results_with_rerank[:request.max_results]
        
        # --- End of new minimalist solution ---

        # Prepare context for OpenAI
        context_texts = []
        sources_for_response: List[SearchResult] = [] # Use explicit type hint for clarity

        logger.info(f"Search results after rerank: {len(search_results)}")
        
        # Filter out low confidence results (less than 30%)
        filtered_results = [result for result in search_results if result.score >= 0.3]
        logger.info(f"Filtered results (confidence >= 30%): {len(filtered_results)}")
        
        # If no results have confidence above 30%, don't use any context
        if not filtered_results:
            logger.info("No high-confidence results found. Returning empty response.")
            event_data = {
                "chatbot_session_id": internal_session_id,
                "event_type": "chat_message", 
                "user_message_text": request.message,
                "bot_response_text": "I don't have enough reliable information to answer your question accurately. Could you please rephrase or ask about a different migraine-related topic?",
                "bot_response_source": {"type": "no_reliable_info"}, # Consistent JSON for DB
                "bot_response_confidence": 0.0,
            }
            db.save_chat_event(event_data)
            logger.debug(f"Event data sent to db.save_chat_event (no_reliable_info): {event_data}") # Debug log
            return ChatResponse(
                response="I apologize, but I couldn't find specific information about that in our MRN Web Designs knowledge base. Please rephrase or ask about website design, development, SEO, digital marketing, or other web design-related topics.",
                source="vector_search",
                confidence=0.0,
                session_id=current_session_uuid,
                source_details={"type": "no_reliable_info"} # Structured data
            )
        
        # Process results and validate URLs
        for result in filtered_results:
            content_preview = result.payload['content']
            original_url = result.payload['url']
            
            # Validate and fix URL before adding to response
            validated_url = validate_and_fix_url(original_url)
            
            # If URL was fixed, log the change
            if validated_url != original_url:
                logger.warning(f"Fixed URL in response: {original_url} -> {validated_url}")
            
            # If no valid URL could be constructed, skip this source or use base URL
            if not validated_url:
                # Try to get base URL from the original
                base_url = get_base_url(original_url)
                if base_url:
                    validated_url = base_url
                    logger.info(f"Using base URL fallback for source: {base_url}")
                else:
                    # Skip this source if no valid URL can be constructed
                    logger.warning(f"Skipping source with invalid URL: {original_url}")
                    continue
            
            context_texts.append(f"Source: {result.payload['source']}\nURL: {validated_url}\n{content_preview}")
            sources.append(SearchResult(
                content=result.payload['content'][:200] + "...",
                source=result.payload['source'],
                url=validated_url,  # Use validated URL
                score=result.score
            ))

        # If all sources were filtered out due to invalid URLs, return appropriate response
        if not sources:
            logger.warning("All sources filtered out due to invalid URLs")
            return ChatResponse(
                response="I found some relevant information, but the source links are currently unavailable. Please contact MRN Web Designs directly for more details about web design and digital marketing services.",
                source="vector_search",
                confidence=filtered_results[0].score if filtered_results else 0.0,
                sources=[]
            )

        # Generate answer using OpenAI
        logger.info(f"Generating answer for query: {request.message}")
        answer = await generate_answer(request.message, context_texts)
        
        # Log chat message (user input + bot response) to the database
        event_data = {
            "chatbot_session_id": internal_session_id,
            "event_type": "chat_message",
            "user_message_text": request.message,
            "bot_response_text": answer,
            "bot_response_source": {"type": "vector_search", "details": {"sources": [s.model_dump() for s in sources_for_response]}}, # Structured JSON for DB
            "bot_response_confidence": filtered_results[0].score if filtered_results else 0.0,
        }
        db.save_chat_event(event_data)
        logger.debug(f"Event data sent to db.save_chat_event (vector_search): {event_data}") # Debug log

        return ChatResponse(
            response=answer,
            sources=sources_for_response, # Use the list of SearchResult objects
            source="vector_search", # Simple string
            confidence=filtered_results[0].score if filtered_results else 0.0,
            session_id=current_session_uuid,
            source_details={"type": "vector_search", "sources": [s.model_dump() for s in sources_for_response]} # Structured data
        )

    except Exception as e:
        logger.exception(f"Error processing chat request: {str(e)}")
        # Log the bot error to the database
        event_data = {
            "chatbot_session_id": internal_session_id,
            "event_type": "chat_message", 
            "user_message_text": request.message,
            "bot_response_text": "Sorry, I had trouble getting your answer. Please try again later.",
            "bot_response_source": {"type": "error_handler"}, # Consistent JSON for DB
            "bot_response_confidence": 0.0,
        }
        db.save_chat_event(event_data)
        logger.debug(f"Event data sent to db.save_chat_event (error_handler): {event_data}") # Debug log
        raise HTTPException(status_code=500, detail="Internal server error")

# Health check endpoint
@app.get("/health")
async def health_check():
    status = {"status": "healthy"}
    if qdrant_client is not None:
        try:
            collections = qdrant_client.get_collections().collections
            status["qdrant"] = "connected"
        except Exception as e:
            status["qdrant"] = f"error: {e}"
    else:
        status["qdrant"] = "not available"
    return status

# Global variable to track reindexing jobs
active_reindexing_jobs = {}
job_counter = 0

class ReindexRequest(BaseModel):
    force_restart: Optional[bool] = False
    chunk_size: Optional[int] = None
    batch_size: Optional[int] = None

class ReindexResponse(BaseModel):
    job_id: str
    status: str
    message: str
    estimated_duration: Optional[str] = None

class ReindexStatusResponse(BaseModel):
    job_id: Optional[str]
    status: str
    progress: Optional[Dict[str, Any]] = None
    message: str
    start_time: Optional[str] = None
    elapsed_time: Optional[float] = None

# Replace the old reindex endpoint with an improved version
@app.post("/api/reindex", response_model=ReindexResponse)
async def trigger_reindex(request: ReindexRequest = ReindexRequest()):
    """Trigger a full content reindexing with improved job management"""
    global job_counter, active_reindexing_jobs
    
    try:
        # Check if Qdrant is accessible
        if qdrant_client is None:
            raise HTTPException(
                status_code=503, 
                detail="Qdrant service is not available. Please ensure Qdrant is running."
            )
        
        try:
            collections = qdrant_client.get_collections().collections
            logger.info(f"Successfully connected to Qdrant. Found {len(collections)} collections.")
        except Exception as e:
            logger.error(f"Error connecting to Qdrant before reindexing: {e}")
            raise HTTPException(
                status_code=503, 
                detail=f"Cannot connect to Qdrant database: {e}"
            )
        
        # Check if there's already an active job
        active_jobs = [job for job in active_reindexing_jobs.values() if job["status"] in ["running", "starting"]]
        if active_jobs and not request.force_restart:
            active_job = active_jobs[0]
            return ReindexResponse(
                job_id=active_job["job_id"],
                status="already_running",
                message=f"A reindexing job is already running (ID: {active_job['job_id']}). Use force_restart=true to stop it and start a new one."
            )
        
        # Stop existing jobs if force_restart is True
        if request.force_restart and active_jobs:
            for job in active_jobs:
                job["status"] = "cancelled"
                logger.info(f"Cancelled existing job {job['job_id']}")
        
        # Create new job
        job_counter += 1
        job_id = f"reindex_{job_counter}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        job_info = {
            "job_id": job_id,
            "status": "starting",
            "start_time": datetime.now().isoformat(),
            "message": "Initializing reindexing process...",
            "progress": None,
            "error": None
        }
        
        active_reindexing_jobs[job_id] = job_info
        
        # Create and start the reindexing task
        async def run_reindex_job():
            try:
                job_info["status"] = "running"
                job_info["message"] = "Reindexing in progress..."
                logger.info(f"Starting reindexing job {job_id}")
                
                # Create embedder instance with custom settings if provided
                embedder_instance = Embedder(client=qdrant_client)
                if request.chunk_size:
                    embedder_instance.chunk_size = request.chunk_size
                if request.batch_size:
                    embedder_instance.batch_size = request.batch_size
                
                # Run the reindexing
                result = await embedder_instance.reindex_all_content()
                
                # Update job status
                job_info["status"] = "completed"
                job_info["message"] = "Reindexing completed successfully"
                job_info["result"] = result
                job_info["end_time"] = datetime.now().isoformat()
                
                logger.info(f"Reindexing job {job_id} completed successfully")
                
            except Exception as e:
                job_info["status"] = "failed"
                job_info["message"] = f"Reindexing failed: {str(e)}"
                job_info["error"] = str(e)
                job_info["end_time"] = datetime.now().isoformat()
                logger.error(f"Reindexing job {job_id} failed: {e}")
        
        # Start the job as a background task
        asyncio.create_task(run_reindex_job())
        
        # Estimate duration based on typical processing
        try:
            wp_fetcher = WordPressFetcher()
            posts = wp_fetcher.get_all_posts()
            estimated_minutes = max(1, len(posts) // 20)  # Rough estimate: 20 posts per minute
            estimated_duration = f"~{estimated_minutes} minutes"
        except:
            estimated_duration = "Unknown"
        
        return ReindexResponse(
            job_id=job_id,
            status="started",
            message="Reindexing job started successfully",
            estimated_duration=estimated_duration
        )
        
    except HTTPException:
        # Re-raise HTTP exceptions as they already have proper status codes and details
        raise
    except Exception as e:
        logger.error(f"Error starting reindexing job: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start reindexing: {e}")

@app.get("/api/reindex/status", response_model=ReindexStatusResponse)
async def get_reindex_status(job_id: Optional[str] = None):
    """Get the status of reindexing jobs"""
    try:
        if job_id:
            # Get specific job status
            if job_id not in active_reindexing_jobs:
                raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
            
            job_info = active_reindexing_jobs[job_id]
            
            # Get detailed progress if job is running
            progress = None
            if job_info["status"] == "running":
                try:
                    embedder_instance = Embedder(client=qdrant_client)
                    status_info = embedder_instance.get_indexing_status()
                    progress = status_info.get("progress")
                except Exception as e:
                    logger.warning(f"Could not get detailed progress: {e}")
            
            # Calculate elapsed time
            elapsed_time = None
            if "start_time" in job_info:
                start_time = datetime.fromisoformat(job_info["start_time"])
                elapsed_time = (datetime.now() - start_time).total_seconds()
            
            return ReindexStatusResponse(
                job_id=job_id,
                status=job_info["status"],
                progress=progress,
                message=job_info["message"],
                start_time=job_info.get("start_time"),
                elapsed_time=elapsed_time
            )
        else:
            # Get status of most recent job or overall status
            if not active_reindexing_jobs:
                return ReindexStatusResponse(
                    job_id=None,
                    status="idle",
                    message="No reindexing jobs found"
                )
            
            # Get the most recent job
            recent_job = max(active_reindexing_jobs.values(), key=lambda x: x["start_time"])
            
            # Get detailed progress if job is running
            progress = None
            if recent_job["status"] == "running":
                try:
                    embedder_instance = Embedder(client=qdrant_client)
                    status_info = embedder_instance.get_indexing_status()
                    progress = status_info.get("progress")
                except Exception as e:
                    logger.warning(f"Could not get detailed progress: {e}")
            
            # Calculate elapsed time
            elapsed_time = None
            if "start_time" in recent_job:
                start_time = datetime.fromisoformat(recent_job["start_time"])
                if recent_job["status"] in ["running", "starting"]:
                    elapsed_time = (datetime.now() - start_time).total_seconds()
                elif "end_time" in recent_job:
                    end_time = datetime.fromisoformat(recent_job["end_time"])
                    elapsed_time = (end_time - start_time).total_seconds()
            
            return ReindexStatusResponse(
                job_id=recent_job["job_id"],
                status=recent_job["status"],
                progress=progress,
                message=recent_job["message"],
                start_time=recent_job.get("start_time"),
                elapsed_time=elapsed_time
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting reindex status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get status: {e}")

@app.get("/api/reindex/jobs")
async def list_reindex_jobs():
    """List all reindexing jobs"""
    try:
        jobs = []
        for job_id, job_info in active_reindexing_jobs.items():
            # Calculate elapsed time
            elapsed_time = None
            if "start_time" in job_info:
                start_time = datetime.fromisoformat(job_info["start_time"])
                if job_info["status"] in ["running", "starting"]:
                    elapsed_time = (datetime.now() - start_time).total_seconds()
                elif "end_time" in job_info:
                    end_time = datetime.fromisoformat(job_info["end_time"])
                    elapsed_time = (end_time - start_time).total_seconds()
            
            jobs.append({
                "job_id": job_id,
                "status": job_info["status"],
                "start_time": job_info.get("start_time"),
                "end_time": job_info.get("end_time"),
                "elapsed_time": elapsed_time,
                "message": job_info["message"]
            })
        
        # Sort by start time (most recent first)
        jobs.sort(key=lambda x: x["start_time"] or "", reverse=True)
        
        return {
            "jobs": jobs,
            "total_jobs": len(jobs),
            "active_jobs": len([j for j in jobs if j["status"] in ["running", "starting"]])
        }
    
    except Exception as e:
        logger.error(f"Error listing reindex jobs: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list jobs: {e}")

@app.delete("/api/reindex/jobs/{job_id}")
async def cancel_reindex_job(job_id: str):
    """Cancel a specific reindexing job"""
    try:
        if job_id not in active_reindexing_jobs:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        
        job_info = active_reindexing_jobs[job_id]
        
        if job_info["status"] not in ["running", "starting"]:
            return {
                "job_id": job_id,
                "status": job_info["status"],
                "message": f"Job {job_id} is not running (status: {job_info['status']})"
            }
        
        # Mark job as cancelled
        job_info["status"] = "cancelled"
        job_info["message"] = "Job cancelled by user"
        job_info["end_time"] = datetime.now().isoformat()
        
        logger.info(f"Cancelled reindexing job {job_id}")
        
        return {
            "job_id": job_id,
            "status": "cancelled",
            "message": f"Job {job_id} has been cancelled"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to cancel job: {e}")

# Cleanup old jobs periodically (keep last 10 jobs)
@app.on_event("startup")
async def cleanup_old_jobs():
    """Clean up old job records to prevent memory leaks"""
    async def periodic_cleanup():
        while True:
            try:
                await asyncio.sleep(3600)  # Clean up every hour
                
                if len(active_reindexing_jobs) > 10:
                    # Keep only the 10 most recent jobs
                    jobs_by_time = sorted(
                        active_reindexing_jobs.items(),
                        key=lambda x: x[1].get("start_time", ""),
                        reverse=True
                    )
                    
                    # Remove old jobs
                    for job_id, _ in jobs_by_time[10:]:
                        del active_reindexing_jobs[job_id]
                        logger.info(f"Cleaned up old job record: {job_id}")
                        
            except Exception as e:
                logger.error(f"Error during job cleanup: {e}")
    
    # Start cleanup task
    asyncio.create_task(periodic_cleanup())

# Add global exception handler middleware
@app.middleware("http")
async def exception_handling_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except ConnectionError as e:
        logger.error(f"Connection error: {e}")
        return JSONResponse(
            status_code=503,
            content={"detail": f"Database connection error: {str(e)}"}
        )
    except Exception as e:
        logger.error(f"Unhandled exception: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": f"Internal server error: {str(e)}"}
        )

# Add new endpoint for saving chat history
@app.post("/api/save-history")
async def save_history(request: SaveHistoryRequest):
    try:
        session_data = db.get_or_create_session(request.session_id)
        if not session_data:
            raise HTTPException(status_code=500, detail="Could not create or retrieve session")
        internal_session_id = session_data['id']

        event_data = request.dict(exclude_unset=True)
        event_data["chatbot_session_id"] = internal_session_id
        event_data.pop("session_id") # Remove external session_id as we use internal_session_id

        logger.debug(f"Event data sent to db.save_chat_event (save-history): {event_data}") # Debug log
        if db.save_chat_event(event_data):
            return {"status": "success"}
        else:
            raise HTTPException(status_code=500, detail="Failed to save chat event")
    except Exception as e:
        logger.exception(f"Error in save-history endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Add new endpoint for retrieving chat history
@app.get("/api/chat-history/{session_id}")
async def get_chat_history(session_id: str):
    try:
        history = db.get_chat_history(session_id)
        # Convert datetime objects to string for JSON serialization
        for event in history:
            if 'event_timestamp' in event and isinstance(event['event_timestamp'], datetime):
                event['event_timestamp'] = event['event_timestamp'].isoformat()
        return {"history": history}
    except Exception as e:
        logger.exception(f"Error in chat-history endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/start-session")
async def start_session(request: StartSessionRequest):
    try:
        session_data = db.get_or_create_session(request.session_id)
        logger.info(f"Session data: {session_data}")
        if not session_data:
            raise HTTPException(status_code=500, detail="Could not create or retrieve session")
        return {"session_id": session_data['session_id']}
    except Exception as e:
        logger.exception(f"Error in start-session endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# Run the app
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app", 
        host=os.getenv("API_HOST", "0.0.0.0"), 
        port=int(os.getenv("API_PORT", 8043)),
        reload=False
    ) 