#!/bin/bash
# Migraine.ie AI Chatbot Production Deployment Script

set -e  # Exit on any error

# Set colors for terminal output
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}=== Migraine.ie AI Chatbot Production Deployment ===${NC}"
echo -e "${YELLOW}This script will deploy the application to a production server.${NC}"
echo ""

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Please run this script with sudo or as root${NC}"
  exit 1
fi

# Update system packages
echo -e "${YELLOW}=== Updating system packages ===${NC}"
apt update
apt upgrade -y

# Install dependencies
echo -e "${YELLOW}=== Installing dependencies ===${NC}"
apt install -y git curl wget build-essential python3 python3-pip python3-venv
apt install -y docker.io docker-compose
apt install -y nginx certbot python3-certbot-nginx

# Start and enable Docker
systemctl start docker
systemctl enable docker

# Check if OpenAI API key is set
if [ -z "$OPENAI_API_KEY" ]; then
  echo -e "${YELLOW}Please enter your OpenAI API key:${NC}"
  read OPENAI_API_KEY
fi

# Check if domain is set
if [ -z "$DOMAIN" ]; then
  echo -e "${YELLOW}Please enter your domain name (e.g., example.com):${NC}"
  read DOMAIN
fi

# Create /var/www directory if it doesn't exist
mkdir -p /var/www

# Navigate to directory
cd /var/www

# Check if folder exists, if so take backup
if [ -d "migraine-ai-chatbot" ]; then
  echo -e "${YELLOW}Backing up existing installation...${NC}"
  mv migraine-ai-chatbot migraine-ai-chatbot-backup-$(date +%Y%m%d%H%M%S)
fi

# Clone the repository
echo -e "${YELLOW}=== Cloning repository ===${NC}"
git clone https://github.com/your-username/migraine-ai-chatbot.git
cd migraine-ai-chatbot

# Create backend .env file if not exists
if [ ! -f "backend/.env" ]; then
  echo -e "${YELLOW}=== Creating backend .env file ===${NC}"
  cp backend/.env.example backend/.env
  
  # Update the .env file with the OpenAI API key
  sed -i "s/OPENAI_API_KEY=.*/OPENAI_API_KEY=$OPENAI_API_KEY/" backend/.env
fi

# Create frontend .env file
echo -e "${YELLOW}=== Creating frontend .env file ===${NC}"
echo "REACT_APP_API_URL=/api" > frontend/.env

# Set up Qdrant data directory
echo -e "${YELLOW}=== Setting up Qdrant data directory ===${NC}"
mkdir -p qdrant_data
chown -R 1000:1000 qdrant_data

# Deploy with Docker Compose
echo -e "${YELLOW}=== Deploying with Docker Compose ===${NC}"
docker-compose up -d

# Set up Nginx for SSL
echo -e "${YELLOW}=== Setting up Nginx ===${NC}"

# Create Nginx configuration
cat > /etc/nginx/sites-available/migraine-chatbot << EOF
server {
    listen 80;
    server_name $DOMAIN;

    location / {
        proxy_pass http://localhost:80;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_cache_bypass \$http_upgrade;
    }

    location /api/ {
        proxy_pass http://localhost:8013/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_cache_bypass \$http_upgrade;
    }
}
EOF

# Enable the site
ln -sf /etc/nginx/sites-available/migraine-chatbot /etc/nginx/sites-enabled/
# Remove default site if exists
rm -f /etc/nginx/sites-enabled/default

# Test Nginx configuration
nginx -t

# Reload Nginx
systemctl reload nginx

# Set up SSL with Certbot
echo -e "${YELLOW}=== Setting up SSL with Certbot ===${NC}"
certbot --nginx -d $DOMAIN

# Set up database backup script
echo -e "${YELLOW}=== Setting up database backup script ===${NC}"
cat > /var/www/migraine-ai-chatbot/backup_qdrant.sh << EOF
#!/bin/bash
DATE=\$(date +%Y-%m-%d)
BACKUP_DIR=/var/backups/migraine-chatbot
mkdir -p \$BACKUP_DIR
tar -czf \$BACKUP_DIR/qdrant_data_\$DATE.tar.gz /var/www/migraine-ai-chatbot/qdrant_data
EOF

chmod +x /var/www/migraine-ai-chatbot/backup_qdrant.sh

# Set up cron job for backups
(crontab -l 2>/dev/null; echo "0 1 * * * /var/www/migraine-ai-chatbot/backup_qdrant.sh") | crontab -

# Set up cron job for Let's Encrypt renewal
(crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet") | crontab -

# Final message
echo -e "${GREEN}=== Deployment completed successfully! ===${NC}"
echo -e "${GREEN}Your application is now available at https://$DOMAIN${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Test your application thoroughly"
echo "2. Set up monitoring (if needed)"
echo "3. Make sure you have configured regular backups"
echo ""
echo -e "${YELLOW}If you encounter any issues, check the logs with:${NC}"
echo "docker-compose logs -f" 