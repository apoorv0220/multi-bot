import os
import asyncio
import time
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from qdrant_client import QdrantClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("scheduler.log")
    ]
)
logger = logging.getLogger("migraine-scheduler")

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
        qdrant_host = os.getenv("QDRANT_HOST", "localhost")
        qdrant_port = int(os.getenv("QDRANT_PORT", 6333))
        logger.info(f"Connecting to Qdrant at {qdrant_host}:{qdrant_port}")
        
        # Initialize Qdrant client
        self.qdrant_client = QdrantClient(host=qdrant_host, port=qdrant_port)
        
        # Initialize embedder with client
        self.embedder = Embedder(client=self.qdrant_client)
    
    async def run_indexing(self):
        """Run the reindexing process"""
        logger.info("Starting scheduled reindexing...")
        
        try:
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
        # Test Qdrant connection before starting scheduler
        qdrant_host = os.getenv("QDRANT_HOST", "localhost")
        qdrant_port = int(os.getenv("QDRANT_PORT", 6333))
        test_client = QdrantClient(host=qdrant_host, port=qdrant_port)
        
        # Check connection by listing collections
        collections = test_client.get_collections().collections
        logger.info(f"Successfully connected to Qdrant. Found {len(collections)} collections.")
        
        # Start the scheduler
        scheduler = IndexingScheduler()
        scheduler.start()
        
        # Keep the process running
        asyncio.get_event_loop().run_forever()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler shutting down...")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise 