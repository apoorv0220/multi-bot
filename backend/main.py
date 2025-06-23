import os
import json
import uuid
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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app.log")
    ]
)
logger = logging.getLogger("houseoftiles-chatbot")

# Local imports - use relative imports
try:
    from .embedder import Embedder
    from .wordpress_fetcher import WordPressFetcher
except ImportError:
    # Fallback for direct module execution
    from embedder import Embedder
    from wordpress_fetcher import WordPressFetcher

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI(title="House of Tiles AI Chatbot API", 
              description="API for AI-powered search across House of Tiles content")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For development - update for production
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
    COLLECTION_NAME = os.getenv("COLLECTION_NAME", "houseoftiles_content")
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
    session_id: Optional[str] = None
    max_results: int = 5

class ChatResponse(BaseModel):
    response: str
    source: Optional[str] = None
    confidence: Optional[float] = None
    sources: Optional[List[SearchResult]] = None

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
        # First try to search in House of Tiles content (prioritized)
        houseoftiles_results = qdrant_client.search(
            collection_name=COLLECTION_NAME,
            query_vector=embedding,
            limit=limit,
            score_threshold=0.6,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="source_type",
                        match=models.MatchValue(value="houseoftiles_ie")
                    )
                ]
            )
        )
        
        logger.info(f"Found {len(houseoftiles_results)} houseoftiles.ie results")
        
        # If we don't have enough results from House of Tiles, search external sources
        if len(houseoftiles_results) < limit or max([r.score for r in houseoftiles_results] + [0]) < 0.7:
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
            all_results = houseoftiles_results + external_results
            all_results.sort(key=lambda x: x.score, reverse=True)
            logger.info(f"Added {len(external_results)} external results, total: {len(all_results)}")
            return all_results[:limit]
        
        return houseoftiles_results
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
                {"role": "system", "content": "You are a helpful assistant specialized in tiles, flooring, and home improvement. Your role is to format information found in the context to provide accurate, helpful, and professional information about tiles, flooring solutions, bathroom design, and home renovation. Present this information as if it's directly from House of Tiles, a trusted tile and flooring retailer in Dublin. Focus on product knowledge, design advice, installation guidance, and helping customers make informed decisions for their home or commercial projects."},
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
        # Try fuzzy matching first
        fuzzy_response = fuzzy_matcher.get_response(request.message)
        if fuzzy_response:
            logger.info(f"Fuzzy match found for query: {request.message}")
            return {
                "response": fuzzy_response,
                "source": "fuzzy_match",
                "confidence": 1.0,
                "sources": []
            }
        
        # If no fuzzy match, proceed with vector search
        if qdrant_client is None:
            logger.warning("Qdrant is not available, cannot perform vector search.")
            return {
                "response": "Sorry, our knowledge base is temporarily unavailable. Please try again later or ask a basic question.",
                "source": "unavailable",
                "confidence": 0.0,
                "sources": []
            }

        # Generate embedding for the query
        embedding = await generate_embedding(request.message)
        
        # Search in Qdrant
        search_results = await search_qdrant(embedding, request.max_results)
        
        # Prepare context for OpenAI
        context_texts = []
        sources = []

        logger.info(f"Search results: {len(search_results)}")
        
        # Filter out low confidence results (less than 30%)
        filtered_results = [result for result in search_results if result.score >= 0.3]
        logger.info(f"Filtered results (confidence ≥ 30%): {len(filtered_results)}")
        
        # If no results have confidence above 30%, don't use any context
        if not filtered_results:
            logger.info("No high-confidence results found. Returning empty response.")
            return ChatResponse(
                response="I apologize, but I couldn't find specific information about that in our House of Tiles knowledge base. Please rephrase or ask about tiles, flooring, bathroom solutions, or other home improvement topics.",
                source="vector_search",
                confidence=0.0,
                sources=[]
            )
        
        # Process results
        for result in filtered_results:
            content_preview = result.payload['content']
            context_texts.append(f"Source: {result.payload['source']}\nURL: {result.payload['url']}\n{content_preview}")
            sources.append(SearchResult(
                content=result.payload['content'][:200] + "...",
                source=result.payload['source'],
                url=result.payload['url'],
                score=result.score
            ))

        # Generate answer using OpenAI
        logger.info(f"Generating answer for query: {request.message}")
        answer = await generate_answer(request.message, context_texts)
        
        return ChatResponse(
            response=answer,
            source="vector_search",
            confidence=filtered_results[0].score if filtered_results else 0.0,
            sources=sources
        )

    except Exception as e:
        logger.error(f"Error processing chat request: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

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

# Run the app
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app", 
        host=os.getenv("API_HOST", "0.0.0.0"), 
        port=int(os.getenv("API_PORT", 8023)),
        reload=False
    ) 