#!/bin/bash
# Migraine.ie AI Chatbot Monitoring Script

# Set colors for terminal output
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Log file
LOG_FILE="/var/log/migraine-chatbot-monitor.log"

# Function to log messages
log_message() {
  local message="$1"
  local timestamp=$(date "+%Y-%m-%d %H:%M:%S")
  echo "[$timestamp] $message" >> "$LOG_FILE"
  echo -e "$message"
}

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Please run as root or with sudo${NC}"
  exit 1
fi

# Create log file if it doesn't exist
touch "$LOG_FILE"

log_message "${YELLOW}=== Starting Migraine.ie AI Chatbot monitoring ===${NC}"

# Check Docker service
log_message "${YELLOW}Checking Docker service...${NC}"
if ! systemctl is-active --quiet docker; then
  log_message "${RED}Docker service is down. Attempting to restart...${NC}"
  systemctl start docker
  sleep 5
  
  if systemctl is-active --quiet docker; then
    log_message "${GREEN}Docker service successfully restarted${NC}"
  else
    log_message "${RED}Failed to restart Docker service${NC}"
  fi
else
  log_message "${GREEN}Docker service is running${NC}"
fi

# Check Qdrant container
log_message "${YELLOW}Checking Qdrant container...${NC}"
if ! docker ps | grep -q qdrant; then
  log_message "${RED}Qdrant container is not running. Attempting to start...${NC}"
  
  # Check if container exists but is stopped
  if docker ps -a | grep -q qdrant; then
    docker start qdrant
  else
    # If container doesn't exist, try to recreate it
    docker run -d --name qdrant \
      -p 6333:6333 \
      -p 6334:6334 \
      -v /var/www/migraine-ai-chatbot/qdrant_data:/qdrant/storage \
      qdrant/qdrant
  fi
  
  sleep 5
  
  if docker ps | grep -q qdrant; then
    log_message "${GREEN}Qdrant container successfully started${NC}"
  else
    log_message "${RED}Failed to start Qdrant container${NC}"
  fi
else
  log_message "${GREEN}Qdrant container is running${NC}"
fi

# Check all Docker containers from docker-compose
log_message "${YELLOW}Checking all Docker Compose services...${NC}"
cd /var/www/migraine-ai-chatbot

# Get the status of all containers
CONTAINERS=$(docker-compose ps -q)
if [ -z "$CONTAINERS" ]; then
  log_message "${RED}No Docker Compose containers running. Attempting to start all services...${NC}"
  docker-compose up -d
  log_message "${GREEN}Docker Compose services started${NC}"
else
  # Check each container
  for CONTAINER in $(docker-compose ps -q); do
    CONTAINER_NAME=$(docker inspect --format='{{.Name}}' "$CONTAINER" | sed 's/\///')
    CONTAINER_STATE=$(docker inspect --format='{{.State.Status}}' "$CONTAINER")
    
    if [ "$CONTAINER_STATE" != "running" ]; then
      log_message "${RED}Container $CONTAINER_NAME is not running (status: $CONTAINER_STATE). Attempting to restart...${NC}"
      docker-compose restart "$CONTAINER_NAME"
      sleep 3
      
      NEW_STATE=$(docker inspect --format='{{.State.Status}}' "$CONTAINER")
      if [ "$NEW_STATE" == "running" ]; then
        log_message "${GREEN}Container $CONTAINER_NAME successfully restarted${NC}"
      else
        log_message "${RED}Failed to restart container $CONTAINER_NAME${NC}"
      fi
    else
      log_message "${GREEN}Container $CONTAINER_NAME is running${NC}"
    fi
  done
fi

# Check Nginx service
log_message "${YELLOW}Checking Nginx service...${NC}"
if ! systemctl is-active --quiet nginx; then
  log_message "${RED}Nginx service is down. Attempting to restart...${NC}"
  systemctl start nginx
  sleep 2
  
  if systemctl is-active --quiet nginx; then
    log_message "${GREEN}Nginx service successfully restarted${NC}"
  else
    log_message "${RED}Failed to restart Nginx service${NC}"
  fi
else
  log_message "${GREEN}Nginx service is running${NC}"
fi

# Check API endpoint health
log_message "${YELLOW}Checking API health endpoint...${NC}"
API_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8013/health)

if [ "$API_RESPONSE" == "200" ]; then
  log_message "${GREEN}API health check successful${NC}"
else
  log_message "${RED}API health check failed with status code: $API_RESPONSE${NC}"
  log_message "${YELLOW}Restarting backend container...${NC}"
  
  docker-compose restart backend
  sleep 5
  
  NEW_API_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8013/health)
  if [ "$NEW_API_RESPONSE" == "200" ]; then
    log_message "${GREEN}API health check now successful after restart${NC}"
  else
    log_message "${RED}API is still not healthy after restart. Manual intervention required.${NC}"
  fi
fi

# Final message
log_message "${GREEN}=== Monitoring completed ====${NC}"
echo ""
echo -e "${YELLOW}To set up automatic monitoring, add this script to crontab:${NC}"
echo "*/30 * * * * /var/www/migraine-ai-chatbot/monitor.sh > /dev/null 2>&1"
echo ""
echo -e "${YELLOW}View the log file at:${NC} $LOG_FILE" 