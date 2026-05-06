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
QDRANT_HOST = os.getenv("QDRANT_HOST", "houseoftiles-qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))

# Create a shared QdrantClient instance - will be set by main.py
qdrant_client = None

class Embedder:
    def __init__(self, client=None):
        # Use the provided client or the global client
        self.qdrant_client = client or qdrant_client
        
        if self.qdrant_client is None:
            # Connect to Qdrant server if no client provided
            logger.info(f"Creating new Qdrant client connecting to {QDRANT_HOST}:{QDRANT_PORT}")
            self._connect_to_qdrant()
        
        # Collection name for Qdrant
        self.collection_name = os.getenv("COLLECTION_NAME", "houseoftiles_content")
        
        # Embedding model
        self.embedding_model = "text-embedding-3-small"
        
        # Embedding dimension
        self.embedding_dim = 1536  # Dimension for text-embedding-3-small
        
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
    
    async def generate_embedding(self, text):
        """Generate embedding for a given text"""
        try:
            # Better text truncation strategy
            # OpenAI has a limit of about 8192 tokens for text-embedding-3-small
            # Approximate tokens: ~4 chars per token for English text
            max_chars = 7000 * 4  # Use an even safer limit of 7000 tokens
            
            if len(text) > max_chars:
                logger.warning(f"Truncating text from {len(text)} chars to {max_chars} chars")
                
                # Preserve the beginning and end of the content, which are often more important
                # Take 80% from the beginning and 20% from the end for better context
                beginning_portion = int(max_chars * 0.8)
                ending_portion = max_chars - beginning_portion
                
                text = text[:beginning_portion] + "..." + text[-ending_portion:]
                logger.info(f"Text length after truncation: {len(text)} chars")
            
            response = openai.embeddings.create(
                model=self.embedding_model,
                input=text
            )
            
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            # If we still hit token limits, try a more aggressive truncation
            if "maximum context length" in str(e) and len(text) > 5000:
                logger.warning("Attempting more aggressive truncation...")
                shorter_text = text[:5000] + "..." + text[-1000:]  # Only keep 6000 chars total
                try:
                    response = openai.embeddings.create(
                        model=self.embedding_model,
                        input=shorter_text
                    )
                    return response.data[0].embedding
                except Exception as e2:
                    logger.error(f"Error after aggressive truncation: {e2}")
            return None
    
    async def embed_wordpress_content(self, progress_callback=None):
        """Embed WordPress content and store in Qdrant with chunked processing"""
        # Get WordPress content
        wp_fetcher = WordPressFetcher()
        posts = wp_fetcher.get_all_posts()
        
        if not posts:
            logger.warning("No WordPress posts found")
            if progress_callback:
                progress_callback("No WordPress posts found", 0, 0)
            return
        
        logger.info(f"Embedding {len(posts)} WordPress posts...")
        if progress_callback:
            progress_callback(f"Processing {len(posts)} WordPress posts...", 0, len(posts))
        
        logger.info("Clearing existing WordPress content...")
        if progress_callback:
            progress_callback("Clearing existing WordPress content...", 0, len(posts))
        
        self.qdrant_client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="source_type",
                            match=models.MatchValue(value="migraine_ie")
                        )
                    ]
                )
            )
        )
        
        chunk_size = 10
        total_processed = 0
        total_embedded = 0
        
        for i in range(0, len(posts), chunk_size):
            chunk_posts = posts[i:i+chunk_size]
            chunk_points = []
            
            logger.info(f"Processing chunk {i//chunk_size + 1}/{(len(posts) + chunk_size - 1)//chunk_size}")
            if progress_callback:
                progress_callback(f"Processing chunk {i//chunk_size + 1}/{(len(posts) + chunk_size - 1)//chunk_size}", total_processed, len(posts))
            
            for post in chunk_posts:
                try:
                    text = f"{post['title']}\n\n{post['content']}"
                    
                    embedding = await self.generate_embedding(text)
                    
                    if embedding:
                        payload = {
                            "title": post['title'],
                            "content": post['content'],
                            "url": post['url'],
                            "type": post['type'],
                            "date": str(post['date']),
                            "source": "Migraine.ie",
                            "source_type": "migraine_ie"
                        }
                        
                        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"wp_{post['id']}"))
                        
                        point = PointStruct(
                            id=point_id,
                            vector=embedding,
                            payload=payload
                        )
                        
                        chunk_points.append(point)
                        total_embedded += 1
                    
                    total_processed += 1
                    
                except Exception as e:
                    logger.error(f"Error processing post {post.get('id', 'unknown')}: {e}")
                    total_processed += 1
                    continue
            
            if chunk_points:
                try:
                    self.qdrant_client.upsert(
                        collection_name=self.collection_name,
                        points=chunk_points
                    )
                    logger.info(f"Uploaded chunk: {len(chunk_points)} posts")
                    if progress_callback:
                        progress_callback(f"Uploaded {total_embedded} posts so far...", total_processed, len(posts))
                except Exception as e:
                    logger.error(f"Error uploading chunk: {e}")
                    if progress_callback:
                        progress_callback(f"Error uploading chunk: {e}", total_processed, len(posts))
        
        logger.info(f"Successfully embedded {total_embedded} WordPress posts out of {len(posts)} total")
        if progress_callback:
            progress_callback(f"Completed! Embedded {total_embedded} WordPress posts", len(posts), len(posts))
    
    async def embed_external_urls(self, progress_callback=None):
        """Embed content from external URLs and store in Qdrant with chunked processing"""
        wp_fetcher = WordPressFetcher()
        external_urls = wp_fetcher.get_external_urls()
        
        if not external_urls:
            logger.warning("No external URLs found")
            if progress_callback:
                progress_callback("No external URLs found", 0, 0)
            return
        
        logger.info(f"Scraping and embedding {len(external_urls)} external URLs...")
        if progress_callback:
            progress_callback(f"Scraping {len(external_urls)} external URLs...", 0, len(external_urls))
        
        logger.info("Clearing existing external content...")
        if progress_callback:
            progress_callback("Clearing existing external content...", 0, len(external_urls))
        
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
        
        chunk_size = 5
        total_processed = 0
        total_embedded = 0
        
        for i in range(0, len(external_urls), chunk_size):
            chunk_urls = external_urls[i:i+chunk_size]
            
            logger.info(f"Scraping chunk {i//chunk_size + 1}/{(len(external_urls) + chunk_size - 1)//chunk_size}")
            if progress_callback:
                progress_callback(f"Scraping chunk {i//chunk_size + 1}/{(len(external_urls) + chunk_size - 1)//chunk_size}", total_processed, len(external_urls))
            
            try:
                scraped_contents = await scrape_urls(chunk_urls)
                
                chunk_points = []
                
                for content in scraped_contents:
                    try:
                        text = f"{content['title']}\n\n{content['content']}"
                        
                        embedding = await self.generate_embedding(text)
                        
                        if embedding:
                            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, content['url']))
                            
                            point = PointStruct(
                                id=point_id,
                                vector=embedding,
                                payload=content
                            )
                            
                            chunk_points.append(point)
                            total_embedded += 1
                        
                        total_processed += 1
                        
                    except Exception as e:
                        logger.error(f"Error processing external content {content.get('url', 'unknown')}: {e}")
                        total_processed += 1
                        continue
                
                if chunk_points:
                    try:
                        self.qdrant_client.upsert(
                            collection_name=self.collection_name,
                            points=chunk_points
                        )
                        logger.info(f"Uploaded chunk: {len(chunk_points)} external URLs")
                        if progress_callback:
                            progress_callback(f"Uploaded {total_embedded} external URLs so far...", total_processed, len(external_urls))
                    except Exception as e:
                        logger.error(f"Error uploading external chunk: {e}")
                        if progress_callback:
                            progress_callback(f"Error uploading external chunk: {e}", total_processed, len(external_urls))
                
            except Exception as e:
                logger.error(f"Error scraping chunk: {e}")
                if progress_callback:
                    progress_callback(f"Error scraping chunk: {e}", total_processed, len(external_urls))
                total_processed += len(chunk_urls)
        
        logger.info(f"Successfully embedded {total_embedded} external URLs out of {len(external_urls)} total")
        if progress_callback:
            progress_callback(f"Completed! Embedded {total_embedded} external URLs", len(external_urls), len(external_urls))
    
    async def reindex_all_content(self, progress_callback=None):
        """Reindex all content (WordPress posts and external URLs) with progress tracking"""
        logger.info("Starting full content reindexing...")
        if progress_callback:
            progress_callback("Starting full content reindexing...", 0, 100)
        
        try:
            if progress_callback:
                progress_callback("Processing WordPress content...", 10, 100)
            await self.embed_wordpress_content(progress_callback)
            
            if progress_callback:
                progress_callback("Processing external URLs...", 60, 100)
            await self.embed_external_urls(progress_callback)
            
            logger.info("Content reindexing completed")
            if progress_callback:
                progress_callback("Content reindexing completed successfully!", 100, 100)
                
        except Exception as e:
            logger.error(f"Error during reindexing: {e}")
            if progress_callback:
                progress_callback(f"Error during reindexing: {e}", 0, 100)
            raise

# Test function if this module is run directly
async def test_embedder():
    """Test the Embedder class by connecting to the local Qdrant server and testing a simple embedding"""
    embedder = Embedder()
    test_text = "This is a test of the embedding system for House of Tiles"
    embedding = await embedder.generate_embedding(test_text)
    
    if embedding:
        logger.info(f"Successfully generated embedding with {len(embedding)} dimensions")
        return True
    else:
        logger.error("Failed to generate embedding")
        return False

if __name__ == "__main__":
    asyncio.run(test_embedder()) 