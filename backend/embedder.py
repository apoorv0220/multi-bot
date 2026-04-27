import os
import json
import asyncio
import numpy as np
from dotenv import load_dotenv
import openai
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.models import Distance, VectorParams, PointStruct
from qdrant_client.http.exceptions import UnexpectedResponse
import uuid
import logging
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import json
from pathlib import Path

# Configure proper logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("embedder")

# Import local modules with relative imports
try:
    from .wordpress_fetcher import WordPressFetcher
    from .scraper import scrape_urls
except ImportError:
    # Fallback for direct module execution
    from wordpress_fetcher import WordPressFetcher
    from scraper import scrape_urls

# Load environment variables
load_dotenv()

# Initialize OpenAI client
openai.api_key = os.getenv("OPENAI_API_KEY")

# Define Qdrant connection parameters from environment or use defaults
QDRANT_HOST = os.getenv("QDRANT_HOST", "mrnwebdesigns-qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))

# Create a shared QdrantClient instance - will be set by main.py
qdrant_client = None

@dataclass
class ProcessingProgress:
    """Track processing progress for resumption"""
    total_items: int
    processed_items: int = 0
    failed_items: int = 0
    current_batch: int = 0
    start_time: float = 0
    last_update_time: float = 0
    status: str = "pending"  # pending, processing, completed, failed
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_items": self.total_items,
            "processed_items": self.processed_items,
            "failed_items": self.failed_items,
            "current_batch": self.current_batch,
            "start_time": self.start_time,
            "last_update_time": self.last_update_time,
            "status": self.status,
            "progress_percentage": (self.processed_items / self.total_items * 100) if self.total_items > 0 else 0,
            "elapsed_time": time.time() - self.start_time if self.start_time > 0 else 0
        }

class Embedder:
    def __init__(self, client=None, collection_name: Optional[str] = None, source_config: Optional[Dict[str, Any]] = None, progress_callback=None, usage_callback=None):
        # Use the provided client or the global client
        self.qdrant_client = client or qdrant_client
        
        if self.qdrant_client is None:
            # Connect to Qdrant server if no client provided
            logger.info(f"Creating new Qdrant client connecting to {QDRANT_HOST}:{QDRANT_PORT}")
            self._connect_to_qdrant()
        
        # Collection name for Qdrant (tenant-specific should be passed explicitly)
        self.collection_name = collection_name or os.getenv("COLLECTION_NAME")
        if not self.collection_name:
            raise ValueError("collection_name must be provided for multi-tenant indexing")
        self.source_config = source_config or {}
        self.progress_callback = progress_callback
        self.usage_callback = usage_callback
        
        # Embedding model
        self.embedding_model = "text-embedding-3-small"
        
        # Embedding dimension
        self.embedding_dim = 1536  # Dimension for text-embedding-3-small
        
        # Processing configuration
        self.batch_size = int(os.getenv("EMBEDDING_BATCH_SIZE", "10"))  # Process 10 items concurrently
        self.chunk_size = int(os.getenv("EMBEDDING_CHUNK_SIZE", "50"))  # Process in chunks of 50 items
        self.max_retries = int(os.getenv("EMBEDDING_MAX_RETRIES", "3"))
        self.retry_delay = float(os.getenv("EMBEDDING_RETRY_DELAY", "1.0"))
        self.rate_limit_delay = float(os.getenv("EMBEDDING_RATE_LIMIT_DELAY", "0.1"))  # 100ms between API calls
        
        # Progress tracking
        self.progress_file = "indexing_progress.json"
        self.current_progress: Optional[ProcessingProgress] = None
        
        # Ensure collection exists
        self._ensure_collection_exists()
    
    def _connect_to_qdrant(self, max_retries=3, retry_delay=5):
        """Attempt to connect to Qdrant with retries"""
        attempt = 0
        last_error = None
        
        while attempt < max_retries:
            try:
                self.qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
                # Test the connection
                self.qdrant_client.get_collections()
                logger.info(f"Successfully connected to Qdrant at {QDRANT_HOST}:{QDRANT_PORT}")
                return
            except (ConnectionRefusedError, UnexpectedResponse) as e:
                last_error = e
                attempt += 1
                logger.warning(f"Failed to connect to Qdrant (attempt {attempt}/{max_retries}): {e}")
                if attempt < max_retries:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
        
        # If we reached here, we failed to connect after all retries
        logger.error(f"Failed to connect to Qdrant after {max_retries} attempts")
        raise ConnectionError(f"Cannot connect to Qdrant at {QDRANT_HOST}:{QDRANT_PORT}: {last_error}")
    
    def _ensure_collection_exists(self):
        """Ensure that the Qdrant collection exists, create it if it doesn't"""
        try:
            collections = self.qdrant_client.get_collections().collections
            collection_names = [collection.name for collection in collections]
            
            if self.collection_name not in collection_names:
                logger.info(f"Creating collection '{self.collection_name}'")
                self.qdrant_client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=self.embedding_dim,
                        distance=Distance.COSINE
                    )
                )
                
                # Create index for source_type field
                self.qdrant_client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="source_type",
                    field_schema=models.PayloadSchemaType.KEYWORD
                )
                
                logger.info(f"Collection '{self.collection_name}' created successfully")
            else:
                logger.info(f"Collection '{self.collection_name}' already exists")
        except Exception as e:
            logger.error(f"Error ensuring collection exists: {e}")
            raise
    
    async def generate_embedding_with_retry(self, text: str, max_retries: int = None) -> Optional[List[float]]:
        """Generate embedding with retry logic and rate limiting"""
        max_retries = max_retries or self.max_retries
        
        for attempt in range(max_retries):
            try:
                # Rate limiting
                if self.rate_limit_delay > 0:
                    await asyncio.sleep(self.rate_limit_delay)
                
                # Better text truncation strategy
                max_chars = 7000 * 4  # Use an even safer limit of 7000 tokens
                
                if len(text) > max_chars:
                    logger.warning(f"Truncating text from {len(text)} chars to {max_chars} chars")
                    
                    # Preserve the beginning and end of the content, which are often more important
                    beginning_portion = int(max_chars * 0.8)
                    ending_portion = max_chars - beginning_portion
                    
                    text = text[:beginning_portion] + "..." + text[-ending_portion:]
                    logger.debug(f"Text length after truncation: {len(text)} chars")
                
                response = openai.embeddings.create(
                    model=self.embedding_model,
                    input=text
                )
                usage = response.usage or {}
                if self.usage_callback:
                    try:
                        self.usage_callback(
                            {
                                "model_name": self.embedding_model,
                                "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                                "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
                                "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
                            }
                        )
                    except Exception as usage_err:
                        logger.warning(f"Usage callback failed: {usage_err}")
                
                return response.data[0].embedding
                
            except Exception as e:
                logger.warning(f"Embedding generation attempt {attempt + 1}/{max_retries} failed: {e}")
                
                if "rate limit" in str(e).lower():
                    # Rate limit hit, wait longer
                    wait_time = (2 ** attempt) * 2  # Exponential backoff
                    logger.info(f"Rate limit hit, waiting {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                elif "maximum context length" in str(e) and len(text) > 5000:
                    # Try more aggressive truncation
                    logger.warning("Attempting more aggressive truncation...")
                    shorter_text = text[:5000] + "..." + text[-1000:]
                    try:
                        response = openai.embeddings.create(
                            model=self.embedding_model,
                            input=shorter_text
                        )
                        usage = response.usage or {}
                        if self.usage_callback:
                            try:
                                self.usage_callback(
                                    {
                                        "model_name": self.embedding_model,
                                        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                                        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
                                        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
                                    }
                                )
                            except Exception as usage_err:
                                logger.warning(f"Usage callback failed: {usage_err}")
                        return response.data[0].embedding
                    except Exception as e2:
                        logger.error(f"Error after aggressive truncation: {e2}")
                        if attempt == max_retries - 1:
                            return None
                else:
                    # Other error, wait and retry
                    if attempt < max_retries - 1:
                        wait_time = self.retry_delay * (2 ** attempt)
                        await asyncio.sleep(wait_time)
        
        logger.error(f"Failed to generate embedding after {max_retries} attempts")
        return None

    async def generate_embedding(self, text):
        """Backward compatibility method"""
        return await self.generate_embedding_with_retry(text)

    def save_progress(self, progress: ProcessingProgress):
        """Save progress to file for resumption"""
        try:
            with open(self.progress_file, 'w') as f:
                json.dump(progress.to_dict(), f, indent=2)
        except Exception as e:
            logger.error(f"Error saving progress: {e}")

    def load_progress(self) -> Optional[ProcessingProgress]:
        """Load progress from file"""
        try:
            if Path(self.progress_file).exists():
                with open(self.progress_file, 'r') as f:
                    data = json.load(f)
                    progress = ProcessingProgress(
                        total_items=data["total_items"],
                        processed_items=data["processed_items"],
                        failed_items=data["failed_items"],
                        current_batch=data["current_batch"],
                        start_time=data["start_time"],
                        last_update_time=data["last_update_time"],
                        status=data["status"]
                    )
                    return progress
        except Exception as e:
            logger.error(f"Error loading progress: {e}")
        return None

    def clear_progress(self):
        """Clear progress file"""
        try:
            if Path(self.progress_file).exists():
                Path(self.progress_file).unlink()
        except Exception as e:
            logger.error(f"Error clearing progress: {e}")

    async def process_posts_batch(self, posts_batch: List[Dict], batch_num: int) -> List[PointStruct]:
        """Process a batch of posts concurrently"""
        logger.info(f"Processing batch {batch_num} with {len(posts_batch)} posts")
        
        # Create semaphore to limit concurrency
        semaphore = asyncio.Semaphore(self.batch_size)
        
        async def process_single_post(post: Dict) -> Optional[PointStruct]:
            async with semaphore:
                try:
                    # Prepare text for embedding (title + content)
                    text = f"{post['title']}\n\n{post['content']}"
                    
                    # Generate embedding
                    embedding = await self.generate_embedding_with_retry(text)
                    
                    if embedding:
                        # Payload data for Qdrant
                        payload = {
                            "title": post['title'],
                            "content": post['content'],
                            "url": post['url'],
                            "type": post['type'],
                            "date": str(post['date']),
                            "source": "MRN Web Designs",
                            "source_type": "mrnwebdesigns_ie"  # Used for filtering
                        }
                        
                        # Create point with UUID format
                        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"wp_{post['id']}"))
                        
                        point = PointStruct(
                            id=point_id,
                            vector=embedding,
                            payload=payload
                        )
                        
                        logger.debug(f"Successfully processed post: {post['title'][:50]}...")
                        return point
                    else:
                        logger.warning(f"Failed to generate embedding for post: {post['title'][:50]}...")
                        return None
                        
                except Exception as e:
                    logger.error(f"Error processing post {post.get('title', 'Unknown')}: {e}")
                    return None
        
        # Process all posts in the batch concurrently
        tasks = [process_single_post(post) for post in posts_batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out None results and exceptions
        valid_points = []
        failed_count = 0
        
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Task failed with exception: {result}")
                failed_count += 1
            elif result is not None:
                valid_points.append(result)
            else:
                failed_count += 1
        
        logger.info(f"Batch {batch_num} completed: {len(valid_points)} successful, {failed_count} failed")
        return valid_points

    async def embed_wordpress_content_chunked(self) -> Dict[str, Any]:
        """Embed WordPress content in chunks to prevent timeouts"""
        logger.info("Starting chunked WordPress content embedding...")
        
        # Get WordPress content
        wp_fetcher = WordPressFetcher(source_config=self.source_config)
        posts = wp_fetcher.get_all_posts()
        
        if not posts:
            logger.warning("No WordPress posts found")
            return {"status": "completed", "message": "No posts to process"}
        
        total_posts = len(posts)
        logger.info(f"Found {total_posts} WordPress posts to process")
        
        # Initialize or load progress
        self.current_progress = self.load_progress()
        if self.current_progress is None or self.current_progress.status == "completed":
            self.current_progress = ProcessingProgress(total_items=total_posts)
            self.current_progress.start_time = time.time()
            self.current_progress.status = "processing"
        
        # Clear existing WordPress content first (only once)
        if self.current_progress.processed_items == 0:
            logger.info("Clearing existing WordPress content...")
            try:
                self.qdrant_client.delete(
                    collection_name=self.collection_name,
                    points_selector=models.FilterSelector(
                        filter=models.Filter(
                            must=[
                                models.FieldCondition(
                                    key="source_type",
                                    match=models.MatchValue(value="mrnwebdesigns_ie")
                                )
                            ]
                        )
                    )
                )
                logger.info("Cleared existing WordPress content")
            except Exception as e:
                logger.error(f"Error clearing existing content: {e}")
        
        # Process posts in chunks
        all_points = []
        chunk_start = self.current_progress.current_batch * self.chunk_size
        
        for chunk_num in range(self.current_progress.current_batch, (total_posts + self.chunk_size - 1) // self.chunk_size):
            start_idx = chunk_num * self.chunk_size
            end_idx = min(start_idx + self.chunk_size, total_posts)
            chunk_posts = posts[start_idx:end_idx]
            
            logger.info(f"Processing chunk {chunk_num + 1}: posts {start_idx + 1} to {end_idx} of {total_posts}")
            
            # Process chunk in smaller batches
            chunk_points = []
            for batch_start in range(0, len(chunk_posts), self.batch_size):
                batch_end = min(batch_start + self.batch_size, len(chunk_posts))
                batch_posts = chunk_posts[batch_start:batch_end]
                
                batch_points = await self.process_posts_batch(batch_posts, chunk_num * 10 + batch_start // self.batch_size)
                chunk_points.extend(batch_points)
                
                # Update progress
                self.current_progress.processed_items += len(batch_posts)
                self.current_progress.failed_items += len(batch_posts) - len(batch_points)
                self.current_progress.last_update_time = time.time()
                self.save_progress(self.current_progress)
                if self.progress_callback:
                    try:
                        self.progress_callback(self.current_progress.to_dict())
                    except Exception as cb_err:
                        logger.warning(f"Progress callback failed: {cb_err}")
                
                logger.info(f"Progress: {self.current_progress.processed_items}/{total_posts} posts processed ({self.current_progress.processed_items/total_posts*100:.1f}%)")
            
            # Upload chunk to Qdrant
            if chunk_points:
                try:
                    # Upload in smaller batches to Qdrant
                    qdrant_batch_size = 100
                    for i in range(0, len(chunk_points), qdrant_batch_size):
                        batch_for_qdrant = chunk_points[i:i+qdrant_batch_size]
                        self.qdrant_client.upsert(
                            collection_name=self.collection_name,
                            points=batch_for_qdrant
                        )
                        logger.info(f"Uploaded {len(batch_for_qdrant)} points to Qdrant (batch {i//qdrant_batch_size + 1})")
                    
                    all_points.extend(chunk_points)
                    logger.info(f"Chunk {chunk_num + 1} completed: {len(chunk_points)} points uploaded")
                    
                except Exception as e:
                    logger.error(f"Error uploading chunk {chunk_num + 1} to Qdrant: {e}")
                    # Continue with next chunk instead of failing completely
            
            # Update chunk progress
            self.current_progress.current_batch = chunk_num + 1
            self.save_progress(self.current_progress)
            
            # Small delay between chunks to prevent overwhelming the system
            await asyncio.sleep(0.5)
        
        # Mark as completed
        self.current_progress.status = "completed"
        self.current_progress.last_update_time = time.time()
        self.save_progress(self.current_progress)
        
        result = {
            "status": "completed",
            "total_posts": total_posts,
            "successful_embeddings": len(all_points),
            "failed_embeddings": self.current_progress.failed_items,
            "processing_time": time.time() - self.current_progress.start_time
        }
        
        logger.info(f"WordPress content embedding completed: {result}")
        return result

    # Keep the original method for backward compatibility
    async def embed_wordpress_content(self):
        """Embed WordPress content and store in Qdrant (chunked version)"""
        result = await self.embed_wordpress_content_chunked()
        logger.info(f"Successfully embedded WordPress posts: {result}")
    
    async def embed_external_urls(self):
        """Embed content from external URLs and store in Qdrant"""
        # Get external URLs from WordPress
        wp_fetcher = WordPressFetcher(source_config=self.source_config)
        external_urls = wp_fetcher.get_external_urls()
        
        if not external_urls:
            logger.warning("No external URLs found")
            return
        
        logger.info(f"Scraping and embedding {len(external_urls)} external URLs...")
        
        # Scrape URLs
        scraped_contents = await scrape_urls(external_urls)
        
        # Process scraped content
        points = []
        
        for content in scraped_contents:
            # Prepare text for embedding (title + content)
            text = f"{content['title']}\n\n{content['content']}"
            
            # Generate embedding
            embedding = await self.generate_embedding_with_retry(text)
            
            if embedding:
                # Create point with proper UUID
                # Create a deterministic UUID based on the URL
                point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, content['url']))
                
                point = PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload=content
                )
                
                points.append(point)
        
        if points:
            # First, delete all existing external content
            self.qdrant_client.delete(
                collection_name=self.collection_name,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="source_type",
                                match=models.MatchValue(value="external")
                            )
                        ]
                    )
                )
            )
            
            # Upload new points in batches
            batch_size = 100
            for i in range(0, len(points), batch_size):
                batch_points = points[i:i+batch_size]
                self.qdrant_client.upsert(
                    collection_name=self.collection_name,
                    points=batch_points
                )
                logger.info(f"Uploaded {min(i+batch_size, len(points))}/{len(points)} external URLs")
        
        logger.info(f"Successfully embedded {len(points)} external URLs")
    
    async def reindex_all_content(self):
        """Reindex all content with chunked processing to prevent timeouts"""
        logger.info("Starting chunked full content reindexing...")
        
        try:
            # Embed WordPress content with chunking
            wp_result = await self.embed_wordpress_content_chunked()
            
            # Embed external URLs (this is usually smaller, so keep as is for now)
            await self.embed_external_urls()
            
            # Clear progress file on successful completion
            self.clear_progress()
            
            logger.info("Chunked content reindexing completed successfully")
            return {
                "status": "completed",
                "wordpress_result": wp_result,
                "message": "All content reindexed successfully"
            }
            
        except Exception as e:
            logger.error(f"Error during chunked reindexing: {e}")
            if self.current_progress:
                self.current_progress.status = "failed"
                self.save_progress(self.current_progress)
            raise

    def get_indexing_status(self) -> Dict[str, Any]:
        """Get current indexing status"""
        progress = self.load_progress()
        if progress is None:
            return {
                "status": "idle",
                "message": "No indexing process running"
            }
        
        return {
            "status": progress.status,
            "progress": progress.to_dict(),
            "message": f"Processing {progress.processed_items}/{progress.total_items} items"
        }

# Test function if this module is run directly
async def test_embedder():
    """Test the Embedder class by connecting to the local Qdrant server and testing a simple embedding"""
    embedder = Embedder()
    test_text = "This is a test of the embedding system for MRN Web Designs"
    embedding = await embedder.generate_embedding(test_text)
    
    if embedding:
        logger.info(f"Successfully generated embedding with {len(embedding)} dimensions")
        return True
    else:
        logger.error("Failed to generate embedding")
        return False

if __name__ == "__main__":
    asyncio.run(test_embedder()) 