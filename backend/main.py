import asyncio
import os
import json
import uuid
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
logger = logging.getLogger("migraine-chatbot")

# Local imports - use relative imports
from scraper import WebScraper

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI(title="Migraine.ie AI Chatbot API", 
              description="API for AI-powered search across Migraine.ie content")

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
try:
    # Define Qdrant connection parameters from environment or use defaults
    QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
    QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
    COLLECTION_NAME = os.getenv("COLLECTION_NAME", "migraine_content")
    logger.info(f"Connecting to Qdrant at {QDRANT_HOST}:{QDRANT_PORT}")
    qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    # Check if collection exists, create if not
    collections = qdrant_client.get_collections().collections
    collection_names = [collection.name for collection in collections]
    if COLLECTION_NAME not in collection_names:
        logger.info(f"Creating collection '{COLLECTION_NAME}'...")
        qdrant_client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(
                size=1536,  # Dimension for text-embedding-3-small
                distance=Distance.COSINE
            )
        )
        qdrant_client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="source_type",
            field_schema=models.PayloadSchemaType.KEYWORD
        )
        logger.info(f"Collection '{COLLECTION_NAME}' created")
except Exception as e:
    logger.error(f"Qdrant unavailable or error initializing: {e}")
    qdrant_client = None

# Share the client with the embedder module
import embedder as embedder_module
embedder_module.qdrant_client = qdrant_client

# Initialize fuzzy matcher
fuzzy_matcher = FuzzyMatcher(threshold=80)

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
    
    try:
        # First try to search in Migraine.ie content (prioritized)
        migraine_results = qdrant_client.search(
            collection_name=COLLECTION_NAME,
            query_vector=embedding,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="source_type",
                        match=models.MatchValue(value="migraine_ie")
                    )
                ]
            ),
            limit=limit
        )

        logger.info(f"Found {len(migraine_results)} migraine.ie results")
        
        # If we don't have enough results with high confidence, search in external sources
        if len(migraine_results) < limit or max([r.score for r in migraine_results] + [0]) < 0.7:
            external_results = qdrant_client.search(
                collection_name=COLLECTION_NAME,
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
            all_results = migraine_results + external_results
            all_results.sort(key=lambda x: x.score, reverse=True)
            logger.info(f"Added {len(external_results)} external results, total: {len(all_results)}")
            return all_results[:limit]
        
        return migraine_results
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
                {"role": "system", "content": "You are a helpful assistant specialized in migraines. Your role is to format information found in the context to provide accurate, concise, and compassionate information. Present this information as if it's directly from the source materials, not as your own analysis. Use a factual tone like a medical publication. Structure your response to reflect the information from the context in a coherent, organized manner. If the context doesn't contain the information needed, simply say the information isn't available."},
                {"role": "user", "content": f"Question: {query}\n\nContext: {context}"}
            ]
        )
        
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error generating answer: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate answer")

# API endpoint for the chat query
@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> Dict[str, Any]:
    """
    Handle chat requests with fuzzy matching for common queries.
    Falls back to vector search if no fuzzy match is found.
    """
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
            # Log chat message (user input + bot response) to the database
            event_data = {
                "chatbot_session_id": internal_session_id,
                "event_type": "chat_message", 
                "user_message_text": request.message,
                "bot_response_text": fuzzy_response,
                "bot_response_source": {"type": "fuzzy_match"}, # Consistent JSON for DB
                "bot_response_confidence": 1.0,
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
            logger.warning("Qdrant is not available, cannot perform vector search.")
            event_data = {
                "chatbot_session_id": internal_session_id,
                "event_type": "chat_message", 
                "user_message_text": request.message,
                "bot_response_text": "Sorry, our knowledge base is temporarily unavailable. Please try again later or ask a basic question.",
                "bot_response_source": {"type": "qdrant_unavailable"}, # Consistent JSON for DB
                "bot_response_confidence": 0.0,
            }
            db.save_chat_event(event_data)
            logger.debug(f"Event data sent to db.save_chat_event (qdrant_unavailable): {event_data}") # Debug log
            return ChatResponse(
                response="Sorry, our knowledge base is temporarily unavailable. Please try again later or ask a basic question.",
                source="qdrant_unavailable", # Simple string
                confidence=0.0,
                sources=[],
                session_id=current_session_uuid,
                source_details={"type": "qdrant_unavailable"} # Structured data
            )
        
        # Generate embedding for the query
        embedding = await generate_embedding(request.message)
        
        # Search in Qdrant
        search_results = await search_qdrant(embedding, request.max_results)
        
        # Prepare context for OpenAI
        context_texts = []
        sources_for_response: List[SearchResult] = [] # Use explicit type hint for clarity

        logger.info(f"Search results: {len(search_results)}")
        
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
                response="I don't have enough reliable information to answer your question accurately. Could you please rephrase or ask about a different migraine-related topic?",
                sources=[],
                source="no_reliable_info", # Simple string
                confidence=0.0,
                session_id=current_session_uuid,
                source_details={"type": "no_reliable_info"} # Structured data
            )
        
        # Process results
        for result in filtered_results:
            content_preview = result.payload['content']
            context_texts.append(f"Source: {result.payload['source']}\nURL: {result.payload['url']}\n{content_preview}")
            sources_for_response.append(SearchResult(
                content=result.payload['content'][:200] + "...",
                source=result.payload['source'],
                url=result.payload['url'],
                score=result.score
            ))

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

# Add a new endpoint to trigger content indexing
@app.post("/api/reindex")
async def trigger_reindex(background_tasks: BackgroundTasks):
    """Trigger a full content reindexing in the background"""
    try:
        # First check if Qdrant is accessible
        try:
            collections = qdrant_client.get_collections().collections
            logger.info(f"Successfully connected to Qdrant. Found {len(collections)} collections.")
        except Exception as e:
            logger.error(f"Error connecting to Qdrant before reindexing: {e}")
            raise HTTPException(
                status_code=503, 
                detail=f"Cannot connect to Qdrant database. Please ensure Qdrant is running: {e}"
            )
        
        # Create function to run in background
        async def run_reindex():
            try:
                logger.info("Starting content reindexing process...")
                embedder_instance = Embedder(client=qdrant_client)
                await embedder_instance.reindex_all_content()
                logger.info("Content reindexing process completed!")
                
            except Exception as e:
                logger.error(f"Error during reindexing process: {e}")
        
        # Add the task to run in the background
        background_tasks.add_task(run_reindex)
        
        return {
            "status": "success", 
            "message": "Content reindexing started in the background"
        }
    except HTTPException:
        # Re-raise HTTP exceptions as they already have proper status codes and details
        raise
    except Exception as e:
        logger.error(f"Error starting reindexing: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start reindexing: {e}")

# Add a new endpoint for chunked reindexing with progress tracking
@app.post("/api/reindex-chunked")
async def trigger_chunked_reindex():
    """Trigger a chunked content reindexing with progress tracking"""
    try:
        # First check if Qdrant is accessible
        try:
            collections = qdrant_client.get_collections().collections
            logger.info(f"Successfully connected to Qdrant. Found {len(collections)} collections.")
        except Exception as e:
            logger.error(f"Error connecting to Qdrant before reindexing: {e}")
            raise HTTPException(
                status_code=503, 
                detail=f"Cannot connect to Qdrant database. Please ensure Qdrant is running: {e}"
            )
        
        # Create a simple progress callback that logs progress
        def progress_callback(message, current, total):
            logger.info(f"Progress: {message} ({current}/{total})")
        
        # Run reindexing with progress tracking
        embedder_instance = Embedder(client=qdrant_client)
        await embedder_instance.reindex_all_content(progress_callback)
        
        return {
            "status": "success", 
            "message": "Content reindexing completed successfully"
        }
    except HTTPException:
        # Re-raise HTTP exceptions as they already have proper status codes and details
        raise
    except Exception as e:
        logger.error(f"Error during reindexing: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to complete reindexing: {e}")

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
        port=int(os.getenv("API_PORT", 8013)),
        reload=False
    ) 