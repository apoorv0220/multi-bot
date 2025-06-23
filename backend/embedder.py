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
    
    async def embed_wordpress_content(self):
        """Embed WordPress content and store in Qdrant"""
        # Get WordPress content
        wp_fetcher = WordPressFetcher()
        posts = wp_fetcher.get_all_posts()
        
        if not posts:
            logger.warning("No WordPress posts found")
            return
        
        logger.info(f"Embedding {len(posts)} WordPress posts...")
        
        # Process each post
        points = []
        
        for post in posts:
            # Prepare text for embedding (title + content)
            text = f"{post['title']}\n\n{post['content']}"
            
            # Generate embedding
            embedding = await self.generate_embedding(text)
            
            if embedding:
                # Payload data for Qdrant
                payload = {
                    "title": post['title'],
                    "content": post['content'],
                    "url": post['url'],
                    "type": post['type'],
                    "date": str(post['date']),
                    "source": "House of Tiles",
                    "source_type": "houseoftiles_ie"  # Used for filtering
                }
                
                # Create point with UUID format
                # Create a deterministic UUID based on the post ID
                point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"wp_{post['id']}"))
                
                point = PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload=payload
                )
                
                points.append(point)
        
        if points:
            # First, delete all existing WordPress content
            self.qdrant_client.delete(
                collection_name=self.collection_name,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="source_type",
                                match=models.MatchValue(value="houseoftiles_ie")
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
                logger.info(f"Uploaded {min(i+batch_size, len(points))}/{len(points)} WordPress posts")
        
        logger.info(f"Successfully embedded {len(points)} WordPress posts")
    
    async def embed_external_urls(self):
        """Embed content from external URLs and store in Qdrant"""
        # Get external URLs from WordPress
        wp_fetcher = WordPressFetcher()
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
            embedding = await self.generate_embedding(text)
            
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
        """Reindex all content (WordPress posts and external URLs)"""
        logger.info("Starting full content reindexing...")
        
        # Embed WordPress content
        await self.embed_wordpress_content()
        
        # Embed external URLs
        await self.embed_external_urls()
        
        logger.info("Content reindexing completed")

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