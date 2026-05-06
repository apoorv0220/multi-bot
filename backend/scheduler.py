import os
import asyncio
import time
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from sqlalchemy import select

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("scheduler.log"),
    ],
)
logger = logging.getLogger("indexing-scheduler")

# Local imports - use relative imports
try:
    from .embedder import Embedder, LEGACY_VECTOR_PRIMARY_SOURCE_LABEL, LEGACY_VECTOR_PRIMARY_SOURCE_TYPE
except ImportError:
    from embedder import Embedder, LEGACY_VECTOR_PRIMARY_SOURCE_LABEL, LEGACY_VECTOR_PRIMARY_SOURCE_TYPE

load_dotenv()


class IndexingScheduler:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.qdrant_host = os.getenv("QDRANT_HOST", "mrnwebdesigns-qdrant")
        self.qdrant_port = int(os.getenv("QDRANT_PORT", 6333))
        logger.info("Connecting to Qdrant at %s:%s", self.qdrant_host, self.qdrant_port)
        self._initialize_qdrant_client()

    def _initialize_qdrant_client(self, max_retries=3, retry_delay=5):
        attempt = 0
        while attempt < max_retries:
            try:
                self.qdrant_client = QdrantClient(host=self.qdrant_host, port=self.qdrant_port)
                self.qdrant_client.get_collections()
                logger.info("Successfully connected to Qdrant server")
                return
            except (ConnectionRefusedError, UnexpectedResponse) as e:
                attempt += 1
                logger.warning("Failed to connect to Qdrant (attempt %s/%s): %s", attempt, max_retries, e)
                if attempt < max_retries:
                    logger.info("Retrying in %s seconds...", retry_delay)
                    time.sleep(retry_delay)
                else:
                    logger.error("Max retries reached. Unable to connect to Qdrant server.")
                    raise

    async def run_indexing(self):
        """Run scheduled reindexing: one tenant at a time with per-tenant Qdrant collection and payload tags."""
        if os.getenv("SCHEDULER_DISABLED", "").strip().lower() in ("1", "true", "yes"):
            logger.info("Scheduled reindex disabled (SCHEDULER_DISABLED).")
            return

        logger.info("Starting scheduled reindexing...")
        try:
            self.qdrant_client.get_collections()
        except Exception as e:
            logger.warning("Connection to Qdrant failed: %s. Reconnecting...", e)
            self._initialize_qdrant_client()

        if os.getenv("SCHEDULER_LEGACY_GLOBAL", "").strip().lower() in ("1", "true", "yes"):
            collection = os.getenv("COLLECTION_NAME", "").strip()
            if not collection:
                logger.error("SCHEDULER_LEGACY_GLOBAL=1 but COLLECTION_NAME is unset; aborting.")
                return
            logger.warning("SCHEDULER_LEGACY_GLOBAL: reindexing single collection %s (not multi-tenant safe).", collection)
            embedder = Embedder(client=self.qdrant_client, collection_name=collection, source_config={})
            await embedder.reindex_all_content()
            logger.info("Legacy global reindex completed.")
            return

        from db import SessionLocal
        from models import Tenant

        import main as app_main

        db = SessionLocal()
        try:
            tenants = db.execute(
                select(Tenant).where(Tenant.status == "active").where(Tenant.source_db_url.isnot(None)).where(Tenant.source_db_url != "")
            ).scalars().all()
            if not tenants:
                logger.info("No active tenants with source_db_url; nothing to reindex.")
                return
            for tenant in tenants:
                tid = str(tenant.id)
                logger.info("Scheduled reindex for tenant %s (%s)", tid, tenant.name)
                source_cfg = app_main._parse_source_dsn(tenant.source_db_url, tenant.source_table_prefix, tenant.source_url_table)
                payload_st = (tenant.widget_source_type or "").strip() or LEGACY_VECTOR_PRIMARY_SOURCE_TYPE
                payload_label = (tenant.brand_name or tenant.name or "").strip() or LEGACY_VECTOR_PRIMARY_SOURCE_LABEL
                url_fb = (tenant.widget_website_url or "").strip() or None
                embedder = Embedder(
                    client=self.qdrant_client,
                    collection_name=app_main._tenant_collection(tid),
                    source_config=source_cfg,
                    vector_payload_source_type=payload_st,
                    vector_payload_source_label=payload_label,
                    url_fallback_base=url_fb,
                )
                await embedder.reindex_all_content()
            logger.info("Scheduled multi-tenant reindexing completed successfully.")
        except Exception as e:
            logger.error("Error during scheduled reindexing: %s", e)
        finally:
            db.close()

    def start(self):
        run_on_start = os.getenv("SCHEDULER_RUN_ON_START", "0").strip().lower() in ("1", "true", "yes")
        self.scheduler.add_job(
            self.run_indexing,
            CronTrigger(day_of_week="sun", hour=2, minute=0),
            id="weekly_reindexing",
            replace_existing=True,
        )
        if run_on_start:
            self.scheduler.add_job(self.run_indexing, id="initial_indexing", replace_existing=True)
        else:
            logger.info("SCHEDULER_RUN_ON_START not enabled: skipping immediate reindex on startup.")

        self.scheduler.start()
        logger.info("Scheduler started. Weekly reindex Sundays 02:00; per-tenant when source_db_url is set.")


if __name__ == "__main__":
    try:
        scheduler = IndexingScheduler()
        scheduler.start()
        asyncio.get_event_loop().run_forever()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler shutting down...")
    except Exception as e:
        logger.error("Unexpected error in scheduler: %s", e)
        raise
