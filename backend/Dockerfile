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
EXPOSE 8000

# Set the default command (uvicorn for development, gunicorn for production)
ENV PYTHONPATH=/app
ENV ENVIRONMENT=production

# Use gunicorn for production
CMD ["gunicorn", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "main:app", "--bind", "0.0.0.0:8000"] 