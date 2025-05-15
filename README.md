# 🧠 AI Search Chatbot – Migraine.ie

This project is a smart, self-hosted AI chatbot that can be embedded into the Migraine.ie WordPress website. It allows users to search across Migraine.ie content and other credible external sources to get instant AI-powered answers. Built with React, Python, and Qdrant.

---

## 🔧 Tech Stack

| Layer           | Technology                                 |
|----------------|---------------------------------------------|
| Frontend        | React.js (JavaScript Widget)               |
| Backend         | Python (FastAPI / Flask)                   |
| Vector DB       | Self-hosted Qdrant                         |
| Embeddings      | OpenAI `text-embedding-3-small`            |
| Content Source  | WordPress MySQL DB + External URLs         |
| Scraping        | Python (Requests, BeautifulSoup, Playwright) |
| Deployment      | Docker + Cron Jobs (for scheduled indexing) |

---

## 📦 Features

- 🔍 **AI-powered search** across Migraine.ie WordPress content
- 🌐 **Additional credible sources** via URLs managed in WordPress DB
- 🔁 **Weekly automatic re-indexing** of both WordPress and external URLs
- 💬 React-based **floating chatbot widget** for easy website integration
- 🔐 Environment-based config for secure credentials
- 🧠 Prioritized search (Migraine content > External sources)
- ✅ Fallback logic and source confidence scoring
- 📄 Optional citations & answer source highlighting

---

## 📁 Folder Structure

```bash
ai-chatbot/
│
├── backend/                # Python API & embedding logic
│   ├── main.py             # FastAPI/Flask app
│   ├── scraper.py          # Web scraping logic for external URLs
│   ├── wordpress_fetcher.py# Pulls content from WordPress DB
│   ├── embedder.py         # Embedding and Qdrant logic
│   └── .env                # Secrets and DB config
│
├── frontend/               # React floating chatbot widget
│   ├── public/
│   ├── src/
│   │   ├── App.js
│   │   └── index.js
│   └── build/              # Build for embedding
│
├── qdrant_data/            # Persistent storage for Qdrant
├── start_migraine_chatbot.sh # Main startup script
├── start_qdrant_docker.sh  # Script to start Qdrant server
├── stop_qdrant_docker.sh   # Script to stop Qdrant server
├── test_qdrant_connection.py # Script to test Qdrant connectivity
├── docker-compose.yml      # Full stack orchestration
├── README.md
└── requirements.txt        # Python dependencies
```

## 🚀 Installation & Setup

### Prerequisites

- Python 3.9+ with pip
- Node.js 16+ with npm
- Docker and Docker Compose (for production deployment)
- An OpenAI API key
- WordPress site with MySQL database

### Quick Start

The easiest way to start the entire application is using the provided startup script:

```bash
# Make sure Docker is running first
./start_migraine_chatbot.sh
```

This script will:
1. Start the Qdrant vector database container
2. Set up a Python virtual environment if needed
3. Launch the backend API server
4. Provide instructions for starting the frontend

### Manual Setup

#### Step 1: Configure environment variables

```bash
cp backend/.env.example backend/.env
# Edit the .env file with your credentials
```

#### Step 2: Start Qdrant Vector Database

You can start the Qdrant server using Docker in one of two ways:

**Option 1: Using the provided script**

```bash
./start_qdrant_docker.sh
```

**Option 2: Using Docker Compose**

```bash
docker-compose up -d qdrant
```

#### Step 3: Backend Setup

```bash
# Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start the backend server
cd backend
python -m uvicorn main:app --reload
```

#### Step 4: Frontend Setup

```bash
# Install Node.js dependencies
cd frontend
npm install

# Start the development server
npm start
```

The chatbot widget will be available at http://localhost:3000

#### Step 5: Test the Qdrant connection

To verify that Qdrant is working correctly:

```bash
python test_qdrant_connection.py
```

### WordPress Integration

1. Upload `frontend/public/migraine-chatbot.php` to your WordPress plugins directory.
2. Activate the "Migraine.ie AI Chatbot" plugin from the WordPress admin dashboard.
3. Configure the plugin settings at WordPress Admin > Migraine Chatbot.
4. Add external URLs to the knowledge base from WordPress Admin > Migraine Chatbot > Custom URLs.

## 🏗️ Production Deployment

For production deployment, use Docker Compose:

```bash
# Build and start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop all services
docker-compose down
```

## 📄 API Documentation

The backend API endpoints can be viewed at http://localhost:8000/docs when the backend is running.

## 📊 Customization Options

- Edit the `.env` file to configure database connections, API keys, and other settings.
- Modify the chatbot appearance by editing the styles in the frontend components.
- Change the indexing schedule in the `scheduler.py` file.

## 🔍 Troubleshooting

- If the chatbot fails to connect to the WordPress database, check your `.env` credentials.
- If the embedding process fails, verify your OpenAI API key and subscription status.
- For Qdrant connectivity issues, run `test_qdrant_connection.py` to diagnose problems.
- Check the logs in `app.log` and `scheduler.log` for detailed error messages.
- Make sure Docker is running before starting the Qdrant container.

## 🛠️ Database Management Tools

Several utility scripts are provided to help manage and inspect the Qdrant vector database:

### Database Inspection
```bash
# Show database contents
./inspect_qdrant_db.py

# Show WordPress content only
./inspect_qdrant_db.py --wp

# Search for specific content
./inspect_qdrant_db.py --search "migraine"
```

### Content Length Issues
If you encounter "context length exceeded" errors when querying:

```bash
# Identify large content
./fix_large_content.py --dry-run

# Fix large content by truncating it
./fix_large_content.py
```

For full documentation of all available database tools, see [QDRANT_TOOLS.md](QDRANT_TOOLS.md).