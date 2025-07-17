FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    software-properties-common \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright dependencies for web scraping
RUN pip install playwright && playwright install chromium

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy backend code
COPY ./backend /app

# Expose the API port
EXPOSE 8033

# Set environment variables
ENV PYTHONPATH=/app
ENV ENVIRONMENT=production

# Production configuration for handling long-running reindexing jobs
ENV GUNICORN_TIMEOUT=3600
ENV GUNICORN_KEEPALIVE=30
ENV GUNICORN_MAX_REQUESTS=1000
ENV GUNICORN_MAX_REQUESTS_JITTER=100
ENV GUNICORN_GRACEFUL_TIMEOUT=300

# Embedding processing configuration
ENV EMBEDDING_BATCH_SIZE=10
ENV EMBEDDING_CHUNK_SIZE=50
ENV EMBEDDING_MAX_RETRIES=3
ENV EMBEDDING_RETRY_DELAY=1.0
ENV EMBEDDING_RATE_LIMIT_DELAY=0.1

# Use gunicorn with production settings optimized for long-running tasks
CMD ["gunicorn", \
     "-w", "2", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8033", \
     "--timeout", "3600", \
     "--keep-alive", "30", \
     "--max-requests", "1000", \
     "--max-requests-jitter", "100", \
     "--graceful-timeout", "300", \
     "--preload", \
     "--log-level", "info", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "main:app"] 