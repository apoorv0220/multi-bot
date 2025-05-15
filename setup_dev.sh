#!/bin/bash
# Migraine.ie AI Chatbot Development Environment Setup Script

set -e  # Exit on any error

# Set colors for terminal output
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}=== Migraine.ie AI Chatbot Development Setup ===${NC}"
echo -e "${YELLOW}This script will set up the development environment.${NC}"
echo ""

# Check if docker is installed
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Docker is not installed. Please install Docker first.${NC}"
    exit 1
fi

# Check if docker-compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}Docker Compose is not installed. Please install Docker Compose first.${NC}"
    exit 1
fi

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Python 3 is not installed. Please install Python 3 first.${NC}"
    exit 1
fi

# Check if Node.js is installed
if ! command -v node &> /dev/null; then
    echo -e "${RED}Node.js is not installed. Please install Node.js first.${NC}"
    exit 1
fi

# Check if OpenAI API key is set
if [ -z "$OPENAI_API_KEY" ]; then
  echo -e "${YELLOW}Please enter your OpenAI API key:${NC}"
  read OPENAI_API_KEY
fi

# Create .env files
echo -e "${YELLOW}=== Creating .env files ===${NC}"

# Backend .env
if [ ! -f "backend/.env" ]; then
  echo -e "${YELLOW}Creating backend/.env${NC}"
  if [ -f "backend/.env.example" ]; then
    cp backend/.env.example backend/.env
    # Update the OpenAI API key
    sed -i '' "s/OPENAI_API_KEY=.*/OPENAI_API_KEY=$OPENAI_API_KEY/" backend/.env
  else
    # Create a basic .env file
    cat > backend/.env << EOF
OPENAI_API_KEY=$OPENAI_API_KEY
QDRANT_HOST=localhost
QDRANT_PORT=6333
COLLECTION_NAME=migraine_content
API_HOST=0.0.0.0
API_PORT=8000
EOF
  fi
else
  echo -e "${YELLOW}backend/.env already exists, skipping${NC}"
fi

# Frontend .env
if [ ! -f "frontend/.env" ]; then
  echo -e "${YELLOW}Creating frontend/.env${NC}"
  cat > frontend/.env << EOF
REACT_APP_API_URL=http://localhost:8000
EOF
else
  echo -e "${YELLOW}frontend/.env already exists, skipping${NC}"
fi

# Set up Python virtual environment
echo -e "${YELLOW}=== Setting up Python virtual environment ===${NC}"
if [ ! -d "venv" ]; then
  python3 -m venv venv
  echo -e "${GREEN}Virtual environment created${NC}"
else
  echo -e "${YELLOW}Virtual environment already exists, skipping${NC}"
fi

# Activate virtual environment and install dependencies
echo -e "${YELLOW}=== Installing Python dependencies ===${NC}"
source venv/bin/activate
pip install -r requirements.txt
echo -e "${GREEN}Python dependencies installed${NC}"

# Install frontend dependencies
echo -e "${YELLOW}=== Installing Node.js dependencies ===${NC}"
if [ -d "frontend" ]; then
  cd frontend
  npm install
  cd ..
  echo -e "${GREEN}Node.js dependencies installed${NC}"
else
  echo -e "${RED}Frontend directory not found, skipping${NC}"
fi

# Start Qdrant
echo -e "${YELLOW}=== Starting Qdrant database ===${NC}"
if [ -f "start_qdrant_docker.sh" ]; then
  chmod +x start_qdrant_docker.sh
  ./start_qdrant_docker.sh
  echo -e "${GREEN}Qdrant database started${NC}"
else
  echo -e "${YELLOW}Creating Qdrant data directory${NC}"
  mkdir -p qdrant_data
  
  echo -e "${YELLOW}Starting Qdrant with Docker${NC}"
  docker run -d --name qdrant \
    -p 6333:6333 \
    -p 6334:6334 \
    -v $(pwd)/qdrant_data:/qdrant/storage \
    qdrant/qdrant
  echo -e "${GREEN}Qdrant database started${NC}"
fi

# Test Qdrant connection
echo -e "${YELLOW}=== Testing Qdrant connection ===${NC}"
if [ -f "test_qdrant_connection.py" ]; then
  python3 test_qdrant_connection.py
  echo -e "${GREEN}Qdrant connection test completed${NC}"
else
  echo -e "${YELLOW}Qdrant connection test script not found, skipping${NC}"
  # Simple connection test
  echo -e "${YELLOW}Attempting simple connection test${NC}"
  curl -s http://localhost:6333/collections > /dev/null
  if [ $? -eq 0 ]; then
    echo -e "${GREEN}Qdrant connection successful${NC}"
  else
    echo -e "${RED}Failed to connect to Qdrant${NC}"
  fi
fi

# Final instructions
echo -e "${GREEN}=== Development environment setup complete! ===${NC}"
echo ""
echo -e "${YELLOW}To start the backend:${NC}"
echo "source venv/bin/activate"
echo "cd backend"
echo "python -m uvicorn main:app --reload"
echo ""
echo -e "${YELLOW}To start the frontend:${NC}"
echo "cd frontend"
echo "npm start"
echo ""
echo -e "${YELLOW}Happy coding!${NC}" 