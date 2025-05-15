#!/bin/bash

# Exit on error
set -e

echo "Starting Qdrant vector database server using Docker..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
  echo "Error: Docker is not running or not installed."
  echo "Please start Docker and try again."
  exit 1
fi

# Create qdrant_data directory if it doesn't exist
mkdir -p ./qdrant_data

# Pull the latest Qdrant image
echo "Pulling latest Qdrant image..."
docker pull qdrant/qdrant:latest

# Check if container is already running
if docker ps --filter "name=migraine_qdrant" --format '{{.Names}}' | grep -q "migraine_qdrant"; then
  echo "Qdrant is already running."
else
  # Start Qdrant container
  echo "Starting Qdrant container..."
  docker run -d \
    --name migraine_qdrant \
    -p 6333:6333 \
    -p 6334:6334 \
    -v "$(pwd)/qdrant_data:/qdrant/storage" \
    qdrant/qdrant:latest
  
  echo "Waiting for Qdrant to start..."
  sleep 5
fi

# Check if Qdrant is responding
if curl -s http://localhost:6333/healthz > /dev/null; then
  echo "Qdrant is running and healthy!"
  echo "REST API: http://localhost:6333"
  echo "Dashboard: http://localhost:6333/dashboard"
  echo "gRPC API: localhost:6334"
else
  echo "Warning: Qdrant container started but not responding to health checks."
  echo "Check container logs with: docker logs migraine_qdrant"
fi 