#!/bin/bash

# Exit on error
set -e

echo "Stopping Qdrant Docker container..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
  echo "Error: Docker is not running or not installed."
  exit 1
fi

# Check if container exists
if docker ps -a --filter "name=migraine_qdrant" --format '{{.Names}}' | grep -q "migraine_qdrant"; then
  # Stop the container
  docker stop migraine_qdrant
  echo "Qdrant container stopped."
  
  # Ask if user wants to remove the container
  read -p "Do you want to remove the Qdrant container? (y/n): " answer
  if [[ "$answer" == "y" || "$answer" == "Y" ]]; then
    docker rm migraine_qdrant
    echo "Qdrant container removed."
  else
    echo "Qdrant container stopped but not removed."
  fi
else
  echo "No Qdrant container found."
fi 