#!/bin/bash

# Exit on error
set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== MIGRAINE.IE CHATBOT STARTUP ===${NC}"
echo "Starting all services for the Migraine.ie AI Chatbot..."
echo

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
  echo -e "${RED}Error: Docker is not running or not installed.${NC}"
  echo "Please start Docker and try again."
  exit 1
fi

# Check if Python virtual environment is activated
if [[ -z "$VIRTUAL_ENV" ]]; then
  echo -e "${YELLOW}Warning: Python virtual environment is not activated.${NC}"
  
  # Check if venv directory exists
  if [[ -d "./venv" ]]; then
    echo "Activating existing virtual environment..."
    source ./venv/bin/activate
  else
    echo "Creating and activating a new virtual environment..."
    python -m venv venv
    source ./venv/bin/activate
    
    echo "Installing required Python packages..."
    pip install -r requirements.txt
  fi
fi

# Create data directories if they don't exist
mkdir -p ./qdrant_data

# Start Qdrant Docker container
echo -e "\n${GREEN}=== STARTING QDRANT VECTOR DATABASE ===${NC}"
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

# Test Qdrant connection
echo -e "\n${GREEN}=== TESTING QDRANT CONNECTION ===${NC}"
python test_qdrant_connection.py
if [ $? -ne 0 ]; then
  echo -e "${RED}Error: Failed to connect to Qdrant.${NC}"
  echo "Check the logs above for more details."
  exit 1
fi

# Start the backend service
echo -e "\n${GREEN}=== STARTING BACKEND API ===${NC}"
echo "Starting FastAPI backend..."

# Check if the service is already running on port 8013
if lsof -Pi :8013 -sTCP:LISTEN -t >/dev/null ; then
  echo -e "${YELLOW}Warning: Something is already running on port 8013.${NC}"
  echo "Please close that process first or change the API_PORT in .env"
  exit 1
fi

# Start backend in the background
cd backend
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8013 &
BACKEND_PID=$!
cd ..

echo "Backend running with PID: $BACKEND_PID"
echo "You can access the API documentation at: http://144.217.68.58:8013/docs"

# Optionally start the frontend
echo -e "\n${GREEN}=== FRONTEND INFORMATION ===${NC}"
echo "To start the React frontend, run the following commands in a new terminal:"
echo -e "${YELLOW}cd frontend${NC}"
echo -e "${YELLOW}npm install${NC}"
echo -e "${YELLOW}npm start${NC}"

echo -e "\n${GREEN}=== ALL SERVICES STARTED ===${NC}"
echo "The Migraine.ie AI Chatbot is now running!"
echo "Backend API: http://144.217.68.58:8013"
echo "Qdrant Dashboard: http://144.217.68.58:6333/dashboard"
echo
echo -e "${YELLOW}Press Ctrl+C to stop all services...${NC}"

# Handle shutdown gracefully
function cleanup {
  echo -e "\n${GREEN}Shutting down services...${NC}"
  
  # Kill the backend process
  if ps -p $BACKEND_PID > /dev/null; then
    echo "Stopping backend API..."
    kill $BACKEND_PID
  fi
  
  echo "Services stopped. Docker containers remain running."
  echo "To stop Docker containers, run: ./stop_qdrant_docker.sh"
  exit 0
}

trap cleanup SIGINT SIGTERM

# Keep script running
wait $BACKEND_PID 