import os
import json
import uuid
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import openai
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.models import Distance, VectorParams
import logging

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
app = FastAPI(title="Migraine.ie AI Chatbot API", 
              description="API for AI-powered search across Migraine.ie content")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with actual origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger.info("Initializing services...")

# Initialize OpenAI client
openai.api_key = os.getenv("OPENAI_API_KEY")
logger.info(f"OpenAI API key configured: {openai.api_key[:5]}...{openai.api_key[-4:] if openai.api_key else 'NOT_SET'}")

# Define Qdrant connection parameters from environment or use defaults
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "migraine_content")

# Create a shared Qdrant client instance
logger.info(f"Connecting to Qdrant at {QDRANT_HOST}:{QDRANT_PORT}")
qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

# Share the client with the embedder module
import embedder as embedder_module
embedder_module.qdrant_client = qdrant_client

# Check if collection exists, create if not
logger.info(f"Using collection name: {COLLECTION_NAME}")
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
    
    # Create index for source_type field
    qdrant_client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="source_type",
        field_schema=models.PayloadSchemaType.KEYWORD
    )
    
    logger.info(f"Collection '{COLLECTION_NAME}' created")

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

# Helper function to generate embeddings
async def generate_embedding(text):
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
async def search_qdrant(embedding, limit=5):
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
async def generate_answer(query, context_texts):
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
                {"role": "system", "content": "You are a helpful assistant specialized in migraines. You provide accurate, concise, and compassionate information based on reliable sources. When answering, rely on the provided context. If the context doesn't contain the information needed, simply say you don't have enough information."},
                {"role": "user", "content": f"Question: {query}\n\nContext: {context}"}
            ]
        )
        
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error generating answer: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate answer")

# API endpoint for the chat query
@app.post("/api/query", response_model=QueryResponse)
async def query(request: QueryRequest):
    # Generate embedding for the query
    embedding = await generate_embedding(request.query)
    
    # Search in Qdrant
    search_results = await search_qdrant(embedding, request.max_results)
    
    # Prepare context for OpenAI
    context_texts = []
    sources = []

    logger.info(f"Search results: {len(search_results)}")
    
    for result in search_results:
        # Add only first 3000 chars of content to avoid context length issues
        content_preview = result.payload['content']
        context_texts.append(f"Source: {result.payload['source']}\nURL: {result.payload['url']}\n{content_preview}")
        sources.append(SearchResult(
            content=result.payload['content'][:200] + "...",  # First 200 chars as preview
            source=result.payload['source'],
            url=result.payload['url'],
            score=result.score
        ))

    logger.info(f"Context texts: {context_texts}")
    
    # Generate answer using OpenAI
    logger.info(f"Generating answer for query: {request.query}")
    answer = await generate_answer(request.query, context_texts)
    
    return QueryResponse(answer=answer, sources=sources)

# Health check endpoint
@app.get("/health")
async def health_check():
    try:
        # Check Qdrant connection
        collections = qdrant_client.get_collections().collections
        collection_names = [collection.name for collection in collections]
        
        # Check if our collection exists
        collection_status = "available" if COLLECTION_NAME in collection_names else "not found"
        
        # Check if OpenAI API key is configured
        openai_status = "configured" if openai.api_key else "not configured"
        
        return {
            "status": "ok",
            "qdrant": "connected", 
            "collection": collection_status,
            "openai": openai_status
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail=f"Health check failed: {e}")

# Add a new endpoint to trigger content indexing
@app.post("/api/reindex")
async def trigger_reindex(background_tasks: BackgroundTasks):
    """Trigger a full content reindexing in the background"""
    try:
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
    except Exception as e:
        logger.error(f"Error starting reindexing: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start reindexing: {e}")

# Run the app
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app", 
        host=os.getenv("API_HOST", "0.0.0.0"), 
        port=int(os.getenv("API_PORT", 8000)),
        reload=False
    ) 