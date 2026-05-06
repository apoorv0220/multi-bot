FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright dependencies for web scraping
RUN pip install playwright && playwright install chromium

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy backend code
COPY ./backend /app
RUN chmod +x /app/entrypoint.sh

# Expose the API port
EXPOSE 8043

# Set environment variables
ENV PYTHONPATH=/app
ENV ENVIRONMENT=production

# Embedding processing configuration for chunked reindexing
ENV EMBEDDING_BATCH_SIZE=10
ENV EMBEDDING_CHUNK_SIZE=50
ENV EMBEDDING_MAX_RETRIES=3
ENV EMBEDDING_RETRY_DELAY=1.0
ENV EMBEDDING_RATE_LIMIT_DELAY=0.1

# Use startup script with migration guard
CMD ["/app/entrypoint.sh"]