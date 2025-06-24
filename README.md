# 👁️ Medical Optics AI Chatbot

An intelligent AI chatbot for Medical Optics - a state-of-the-art ophthalmology practice offering patients top-notch facilities designed to provide the highest level of care for their vision health. This chatbot helps patients with eye care questions, appointment scheduling, and understanding medical procedures.

## 🚀 Features

- 🤖 **AI-powered assistance** for tiles, flooring, and home improvement
- 🔍 **Smart search** across Medical Optics content
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
WORDPRESS_URL_TABLE=wp_custom_urls
WORDPRESS_TABLE_PREFIX=wp_

# Qdrant Configuration
QDRANT_HOST=medicaloptics-qdrant
QDRANT_PORT=6333  # Internal Docker port (always 6333)
COLLECTION_NAME=medicaloptics_content

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
- **Frontend**: Open http://localhost:3033
- **Backend API**: Open http://localhost:8033/docs
- **Qdrant Health**: `curl http://localhost:6033/health`

### 5. Initialize Content (Optional)
```bash
# Sync WordPress content if database is configured
curl -X POST http://localhost:8033/api/reindex
```

## 🌐 Using the Chatbot

### Standalone Widget
Access the chatbot directly at: http://localhost:3033


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
docker-compose logs -f medicaloptics-backend
docker-compose logs -f medicaloptics-frontend
docker-compose logs -f medicaloptics-qdrant
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
| `WORDPRESS_DB_HOST` | WordPress database host | - |
| `WORDPRESS_DB_USER` | WordPress database user | - |
| `WORDPRESS_DB_PASSWORD` | WordPress database password | - |
| `WORDPRESS_DB_NAME` | WordPress database name | - |
| `WORDPRESS_URL_TABLE` | Custom URLs table name | `wp_custom_urls` |
| `WORDPRESS_TABLE_PREFIX` | WordPress table prefix | `wp_` |
| `QDRANT_HOST` | Qdrant database host | `qdrant` |
| `QDRANT_PORT` | Qdrant database port (internal) | `6333` |
| `COLLECTION_NAME` | Vector collection name | `medicaloptics_content` |

### Ports
| Service | Port | Description |
|---------|------|-------------|
| Frontend | 3033 | React chatbot widget |
| Backend | 8033 | FastAPI server |
| Qdrant | 6033 | Vector database |

## 🔧 Troubleshooting

### **Qdrant Port Conflicts**

If you're running multiple projects with Qdrant, you have two options:

#### 🔍 **Understanding Docker Port Mapping**
Our configuration uses: `6033:6333`
- **External access** (from host machine): `localhost:6033`
- **Internal Docker communication**: `medicaloptics-qdrant:6333`
- **Why:** Qdrant always runs on port 6333 inside containers, we just map it externally

#### Option 1: Separate Qdrant Instances (Current Setup)
- Medical Optics uses port `6033` externally (maps to internal `6333`)
- Complete isolation between projects

#### Option 2: Shared Qdrant Instance (Alternative)
To use the same Qdrant instance (port 6333) for both projects:

1. **Remove the Qdrant service** from this docker-compose.yml
2. **Update environment variables:**
   ```env
   QDRANT_HOST=medicaloptics-qdrant
   QDRANT_PORT=6333
   COLLECTION_NAME=medicaloptics_content  # Different collection name
   ```
3. **Benefits:** Resource efficient, single Qdrant management
4. **Note:** Both projects share the same Qdrant but use different collections

### Services Won't Start
```bash
# Check Docker is running
docker --version

# Check ports aren't in use
netstat -tlnp | grep -E '(3033|8033|6033)'

# Reset everything
docker-compose down -v
docker-compose up --build -d
```

### API Connection Issues
1. Verify backend is running: `curl http://localhost:8033/health`
2. Check environment variables in `backend/.env`
3. View backend logs: `docker-compose logs medicaloptics-backend`

### No Chat Responses
1. Ensure `OPENAI_API_KEY` is set correctly
2. Check Qdrant is healthy: `curl http://localhost:6033/health`
3. Initialize content: `curl -X POST http://localhost:8033/api/reindex`

## 📚 API Documentation

When the backend is running, visit http://localhost:8033/docs for interactive API documentation.

## 🏭 Production Deployment

For production deployment:
1. Update domain names in environment files
2. Use proper SSL certificates
3. Configure firewalls for ports 3033, 8033
4. Set up monitoring and backups for Qdrant data
5. Use production-grade OpenAI API limits