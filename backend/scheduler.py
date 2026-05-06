import os
import asyncio
import time
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("scheduler.log")
    ]
)
logger = logging.getLogger("mrnwebdesigns-scheduler")

# Local imports - use relative imports
try:
    from .embedder import Embedder
except ImportError:
    # Fallback for direct module execution
    from embedder import Embedder

# Load environment variables
load_dotenv()

class IndexingScheduler:
    def __init__(self):
        # Initialize scheduler
        self.scheduler = AsyncIOScheduler()
        
        # Set up Qdrant client
        self.qdrant_host = os.getenv("QDRANT_HOST", "mrnwebdesigns-qdrant")
        self.qdrant_port = int(os.getenv("QDRANT_PORT", 6333))
        logger.info(f"Connecting to Qdrant at {self.qdrant_host}:{self.qdrant_port}")
        
        # Initialize Qdrant client with retry logic
        self._initialize_qdrant_client()
        
        # Initialize embedder with client
        self.embedder = Embedder(client=self.qdrant_client)
    
    def _initialize_qdrant_client(self, max_retries=3, retry_delay=5):
        """Initialize Qdrant client with retry logic"""
        attempt = 0
        while attempt < max_retries:
            try:
                self.qdrant_client = QdrantClient(host=self.qdrant_host, port=self.qdrant_port)
                # Test connection
                self.qdrant_client.get_collections()
                logger.info("Successfully connected to Qdrant server")
                return
            except (ConnectionRefusedError, UnexpectedResponse) as e:
                attempt += 1
                logger.warning(f"Failed to connect to Qdrant (attempt {attempt}/{max_retries}): {e}")
                if attempt < max_retries:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    logger.error("Max retries reached. Unable to connect to Qdrant server.")
                    raise
    
    async def run_indexing(self):
        """Run the reindexing process"""
        logger.info("Starting scheduled reindexing...")
        
        try:
            # Test connection before reindexing
            try:
                self.qdrant_client.get_collections()
            except Exception as e:
                logger.warning(f"Connection to Qdrant failed: {e}. Attempting to reconnect...")
                self._initialize_qdrant_client()
                # Update embedder with new client
                self.embedder = Embedder(client=self.qdrant_client)
            
            # Run the reindexing
            await self.embedder.reindex_all_content()
            logger.info("Scheduled reindexing completed successfully!")
        except Exception as e:
            logger.error(f"Error during scheduled reindexing: {e}")
    
    def start(self):
        """Start the scheduler with weekly reindexing"""
        # Schedule weekly reindexing (every Sunday at 2 AM)
        self.scheduler.add_job(
            self.run_indexing,
            CronTrigger(day_of_week='sun', hour=2, minute=0),
            id='weekly_reindexing',
            replace_existing=True
        )
        
        # Add a one-time job to run immediately when the service starts
        self.scheduler.add_job(
            self.run_indexing,
            id='initial_indexing',
            replace_existing=True
        )
        
        self.scheduler.start()
        logger.info("Scheduler started. Weekly reindexing scheduled for Sundays at 2 AM")

# For running the scheduler as a standalone process
if __name__ == "__main__":
    try:
        # Start the scheduler
        scheduler = IndexingScheduler()
        scheduler.start()
        
        # Keep the process running
        asyncio.get_event_loop().run_forever()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler shutting down...")
    except Exception as e:
        logger.error(f"Unexpected error in scheduler: {e}")
        raise 