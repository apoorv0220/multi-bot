# 🏠 House of Tiles AI Chatbot

An intelligent AI chatbot for House of Tiles - Dublin's trusted tile and flooring retailer. This chatbot helps customers with tiles, flooring, bathroom design, and home improvement questions.

## 🚀 Features

- 🤖 **AI-powered assistance** for tiles, flooring, and home improvement
- 🔍 **Smart search** across House of Tiles content
- 📱 **Embeddable widget** for any website
- 🏗️ **WordPress integration** ready
- 🐳 **Docker containerized** for easy deployment

## 📋 Prerequisites

- Docker and Docker Compose installed
- OpenAI API key
- WordPress database access (optional, for content syncing)

## 🚀 Quick Start

### 1. Clone the Repository
```bash
git clone <your-repo-url>
cd ai_chatbot
```

### 2. Configure Environment
Copy and edit the environment file:
```bash
cp backend/.env.example backend/.env
```

Edit `backend/.env` with your settings:
```env
# OpenAI Configuration (Required)
OPENAI_API_KEY=your_openai_api_key_here

# WordPress Database (Optional - for content syncing)
WORDPRESS_DB_HOST=your_wordpress_host
WORDPRESS_DB_USER=your_db_username
WORDPRESS_DB_PASSWORD=your_db_password
WORDPRESS_DB_NAME=your_db_name

# Qdrant Configuration
QDRANT_HOST=qdrant
QDRANT_PORT=6333  # Internal Docker port (always 6333)
COLLECTION_NAME=houseoftiles_content

# Environment
ENVIRONMENT=production
```

### 3. Start the Application
```bash
# Build and start all services
docker-compose up --build -d

# Check if services are running
docker-compose ps

# View logs
docker-compose logs -f
```

### 4. Verify Installation
- **Frontend**: Open http://localhost:3023
- **Backend API**: Open http://localhost:8023/docs
- **Qdrant Health**: `curl http://localhost:6023/health`

### 5. Initialize Content (Optional)
```bash
# Sync WordPress content if database is configured
curl -X POST http://localhost:8023/api/reindex
```

## 🌐 Using the Chatbot

### Standalone Widget
Access the chatbot directly at: http://localhost:3023

### Embed in Any Website
Add this code to your website:
```html
<script>
window.HOUSEOFTILES_CHATBOT_CONFIG = {
  baseUrl: 'http://localhost:3023',
  apiUrl: 'http://localhost:8023',
  primaryColor: '#bd1d73'
};

(function() {
  const script = document.createElement('script');
  script.src = window.HOUSEOFTILES_CHATBOT_CONFIG.baseUrl + '/widget.js';
  script.async = true;
  document.body.appendChild(script);
})();
</script>
```

## 🛠️ Development

### Stop Services
```bash
docker-compose down
```

### Rebuild After Changes
```bash
docker-compose down
docker-compose up --build -d
```

### View Logs
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f houseoftiles-backend
docker-compose logs -f houseoftiles-frontend
docker-compose logs -f houseoftiles-qdrant
```

## 📁 Project Structure
```
ai_chatbot/
├── backend/                 # Python FastAPI backend
│   ├── main.py             # Main API server
│   ├── embedder.py         # Text embedding service
│   ├── wordpress_fetcher.py # WordPress content sync
│   ├── fuzzy_matcher.py    # Response matching
│   └── .env.example        # Environment template
├── frontend/               # React frontend
│   ├── src/                # React components
│   ├── public/             # Static files & widget
│   └── package.json        # Dependencies
├── docker-compose.yml      # Docker configuration
└── README.md              # This file
```

## ⚙️ Configuration

### Environment Variables
| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key (required) | - |
| `QDRANT_HOST` | Qdrant database host | `qdrant` |
| `QDRANT_PORT` | Qdrant database port (internal) | `6333` |
| `COLLECTION_NAME` | Vector collection name | `houseoftiles_content` |

### Ports
| Service | Port | Description |
|---------|------|-------------|
| Frontend | 3023 | React chatbot widget |
| Backend | 8023 | FastAPI server |
| Qdrant | 6023 | Vector database |

## 🔧 Troubleshooting

### **Qdrant Port Conflicts**

If you're running multiple projects with Qdrant, you have two options:

#### 🔍 **Understanding Docker Port Mapping**
Our configuration uses: `6023:6333`
- **External access** (from host machine): `localhost:6023`
- **Internal Docker communication**: `houseoftiles-qdrant:6333`
- **Why:** Qdrant always runs on port 6333 inside containers, we just map it externally

#### Option 1: Separate Qdrant Instances (Current Setup)
- House of Tiles uses port `6023` externally (maps to internal `6333`)
- Complete isolation between projects

#### Option 2: Shared Qdrant Instance (Alternative)
To use the same Qdrant instance (port 6333) for both projects:

1. **Remove the Qdrant service** from this docker-compose.yml
2. **Update environment variables:**
   ```env
   QDRANT_HOST=localhost
   QDRANT_PORT=6333
   COLLECTION_NAME=houseoftiles_content  # Different collection name
   ```
3. **Benefits:** Resource efficient, single Qdrant management
4. **Note:** Both projects share the same Qdrant but use different collections

### Services Won't Start
```bash
# Check Docker is running
docker --version

# Check ports aren't in use
netstat -tlnp | grep -E '(3023|8023|6023)'

# Reset everything
docker-compose down -v
docker-compose up --build -d
```

### API Connection Issues
1. Verify backend is running: `curl http://localhost:8023/health`
2. Check environment variables in `backend/.env`
3. View backend logs: `docker-compose logs houseoftiles-backend`

### No Chat Responses
1. Ensure `OPENAI_API_KEY` is set correctly
2. Check Qdrant is healthy: `curl http://localhost:6023/health`
3. Initialize content: `curl -X POST http://localhost:8023/api/reindex`

## 📚 API Documentation

When the backend is running, visit http://localhost:8023/docs for interactive API documentation.

## 🏭 Production Deployment

For production deployment:
1. Update domain names in environment files
2. Use proper SSL certificates
3. Configure firewalls for ports 3023, 8023
4. Set up monitoring and backups for Qdrant data
5. Use production-grade OpenAI API limits