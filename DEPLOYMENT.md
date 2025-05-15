# Migraine.ie AI Chatbot Deployment Guide

This document provides step-by-step instructions for deploying the Migraine.ie AI Chatbot on a production server.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Server Environment Setup](#server-environment-setup)
3. [Git Repository Setup](#git-repository-setup)
4. [Database Deployment](#database-deployment)
5. [Backend Deployment](#backend-deployment)
6. [Frontend Deployment](#frontend-deployment)
7. [Production Deployment with Docker](#production-deployment-with-docker)
8. [Nginx Configuration](#nginx-configuration)
9. [SSL Setup](#ssl-setup)
10. [Monitoring and Maintenance](#monitoring-and-maintenance)

## Prerequisites

Before starting, ensure you have:

- A Linux server (Ubuntu 20.04 LTS recommended)
- Root or sudo access
- Domain name pointed to your server (for production deployment)
- OpenAI API key

## Server Environment Setup

### Update Server and Install Dependencies

```bash
# Update package lists
sudo apt update
sudo apt upgrade -y

# Install essential tools
sudo apt install -y git curl wget build-essential python3 python3-pip python3-venv
sudo apt install -y nodejs npm
sudo apt install -y docker.io docker-compose

# Start and enable Docker
sudo systemctl start docker
sudo systemctl enable docker

# Add your user to the docker group to run docker without sudo
sudo usermod -aG docker $USER
# Log out and log back in for this to take effect
```

### Install Node.js 16+ (if not already installed)

```bash
# Install Node.js 16.x
curl -fsSL https://deb.nodesource.com/setup_16.x | sudo -E bash -
sudo apt install -y nodejs

# Verify installation
node --version
npm --version
```

## Git Repository Setup

### Clone the Repository

```bash
# Navigate to where you want to store the application
cd /var/www/
# Clone your repository
git clone https://github.com/your-username/migraine-ai-chatbot.git
cd migraine-ai-chatbot
```

### Set Up Git Ignore and Environment Variables

```bash
# Copy example environment file
cp backend/.env.example backend/.env
# Edit the environment file with production values
nano backend/.env
```

Update the `.env` file with your production settings:

```
OPENAI_API_KEY=your_openai_api_key
QDRANT_HOST=localhost
QDRANT_PORT=6333
COLLECTION_NAME=migraine_content
API_HOST=0.0.0.0
API_PORT=8000
...
```

## Database Deployment

### Deploy Qdrant with Docker

The most reliable way to deploy Qdrant is using Docker:

```bash
# Create a directory for persistent Qdrant data
mkdir -p qdrant_data
sudo chown -R 1000:1000 qdrant_data

# Start Qdrant container
docker run -d --name qdrant \
    -p 6333:6333 \
    -p 6334:6334 \
    -v $(pwd)/qdrant_data:/qdrant/storage \
    qdrant/qdrant
```

Alternatively, use the included script:

```bash
# Make script executable
chmod +x start_qdrant_docker.sh
# Run the script
./start_qdrant_docker.sh
```

### Verify Qdrant Installation

```bash
# Check if Qdrant is running
curl http://localhost:6333/collections

# Test the connection with the provided script
python3 test_qdrant_connection.py
```

## Backend Deployment

### Set Up Python Virtual Environment

```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Run the Backend API Server

For development or testing:

```bash
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

For production, we'll use Gunicorn:

```bash
# Install Gunicorn
pip install gunicorn

# Start the API with Gunicorn
cd backend
gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app -b 0.0.0.0:8000
```

### Create a Systemd Service for the Backend

```bash
sudo nano /etc/systemd/system/migraine-chatbot-api.service
```

Add the following content:

```
[Unit]
Description=Migraine.ie AI Chatbot API
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/migraine-ai-chatbot/backend
Environment="PATH=/var/www/migraine-ai-chatbot/venv/bin"
EnvironmentFile=/var/www/migraine-ai-chatbot/backend/.env
ExecStart=/var/www/migraine-ai-chatbot/venv/bin/gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app -b 0.0.0.0:8000
Restart=always

[Install]
WantedBy=multi-user.target
```

Activate and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable migraine-chatbot-api
sudo systemctl start migraine-chatbot-api
sudo systemctl status migraine-chatbot-api
```

## Frontend Deployment

### Build the React Frontend

```bash
# Navigate to frontend directory
cd frontend

# Install dependencies
npm install

# Create production build
npm run build
```

### Configure Environment Variables for Frontend

Create a `.env` file in the frontend directory:

```bash
nano frontend/.env
```

Add the following content:

```
REACT_APP_API_URL=https://your-domain.com/api
```

### Deploy Frontend with Nginx

```bash
# Install Nginx if not already installed
sudo apt install -y nginx

# Create Nginx configuration
sudo nano /etc/nginx/sites-available/migraine-chatbot
```

Add the following configuration:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        root /var/www/migraine-ai-chatbot/frontend/build;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://localhost:8000/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }
}
```

Enable the configuration:

```bash
sudo ln -s /etc/nginx/sites-available/migraine-chatbot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

## Production Deployment with Docker

For a fully containerized setup, you can use the provided `docker-compose.yml` file:

```bash
# Make sure you are in the project root
cd /var/www/migraine-ai-chatbot

# Build and start all services
docker-compose up -d

# View logs
docker-compose logs -f
```

## SSL Setup

For secure HTTPS connections, install Certbot and configure SSL:

```bash
# Install Certbot
sudo apt install -y certbot python3-certbot-nginx

# Obtain SSL certificate
sudo certbot --nginx -d your-domain.com

# Test automatic renewal
sudo certbot renew --dry-run
```

## Monitoring and Maintenance

### Scheduled Database Indexing

Set up a cron job to periodically re-index content:

```bash
# Open crontab
crontab -e
```

Add a weekly indexing job:

```
0 0 * * 0 cd /var/www/migraine-ai-chatbot && ./venv/bin/python -m backend.scheduler
```

### Log Rotation

Set up log rotation to manage log files:

```bash
sudo nano /etc/logrotate.d/migraine-chatbot
```

Add the following configuration:

```
/var/www/migraine-ai-chatbot/*.log {
    weekly
    missingok
    rotate 12
    compress
    notifempty
    create 0640 www-data www-data
}
```

### Database Backup

Set up a script to backup the Qdrant database:

```bash
sudo nano /var/www/migraine-ai-chatbot/backup_qdrant.sh
```

Add the following content:

```bash
#!/bin/bash
DATE=$(date +%Y-%m-%d)
BACKUP_DIR=/var/backups/migraine-chatbot
mkdir -p $BACKUP_DIR
tar -czf $BACKUP_DIR/qdrant_data_$DATE.tar.gz /var/www/migraine-ai-chatbot/qdrant_data
```

Make the script executable and set up a cron job:

```bash
chmod +x /var/www/migraine-ai-chatbot/backup_qdrant.sh
crontab -e
```

Add a daily backup job:

```
0 1 * * * /var/www/migraine-ai-chatbot/backup_qdrant.sh
```

## Troubleshooting

### Common Issues

1. **Context Length Issues**:
   If you encounter context length errors, use the `fix_large_content.py` script:
   ```bash
   cd /var/www/migraine-ai-chatbot
   python3 fix_large_content.py
   ```

2. **Qdrant Connection Issues**:
   If Qdrant isn't responding:
   ```bash
   # Check if Qdrant container is running
   docker ps | grep qdrant
   # Restart it if needed
   docker restart qdrant
   ```

3. **Backend API Issues**:
   Check the logs for errors:
   ```bash
   sudo journalctl -u migraine-chatbot-api.service -f
   ```

For additional help, refer to the project documentation or contact the development team. 