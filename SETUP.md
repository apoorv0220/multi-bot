# Migraine.ie AI Chatbot - Setup Guide

This guide will help you set up and run the Migraine.ie AI chatbot on your local machine, and embed it in any web application.

## Backend Setup

### Prerequisites
- Python 3.9+ with pip
- OpenAI API key
- Optional: MySQL database with WordPress content (for WordPress integration)

### Steps

1. **Create a virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Install Playwright browsers** (needed for scraping external websites):
   ```bash
   python -m playwright install chromium
   ```

4. **Configure the environment**:
   - Edit the `backend/.env` file with your configuration:
   
   ```
   # OpenAI Configuration (REQUIRED)
   OPENAI_API_KEY=your_openai_api_key_here

   # Qdrant Configuration (can stay as default for local)
   QDRANT_HOST=localhost
   QDRANT_PORT=6333
   COLLECTION_NAME=migraine_content

   # Optional WordPress Database Configuration
   WORDPRESS_DB_HOST=localhost
   WORDPRESS_DB_PORT=3306
   WORDPRESS_DB_USER=your_db_user
   WORDPRESS_DB_PASSWORD=your_db_password
   WORDPRESS_DB_NAME=your_db_name
   WORDPRESS_URL_TABLE=wp_custom_urls
   ```

5. **Start the backend server**:
   ```bash
   cd backend
   python -m uvicorn main:app --host 0.0.0.0 --port 8013 --reload
   ```
   This will run the API server at http://localhost:8013

6. **Initialize the database** (optional):
   - If you need to populate the vector database with content:
   ```bash
   cd backend
   python -m embedder
   ```

## Frontend Setup

1. **Install Node.js dependencies**:
   ```bash
   cd frontend
   npm install
   ```

2. **Start the development server**:
   ```bash
   npm start
   ```
   This will run the React app at http://localhost:3013

3. **Test the example embed page**:
   - Open http://localhost:3013/example-embed.html in your browser

## Embedding the Chatbot in Your Website

Add this script to any website where you want to embed the chatbot:

```html
<script>
  // Optional configuration
  window.MIGRAINE_CHATBOT_CONFIG = {
    baseUrl: 'http://localhost:3013',       // URL where the chatbot widget is hosted
    apiUrl: 'http://localhost:8013',        // URL of the backend API
    primaryColor: '#5762d5'                 // Primary color for the chatbot
  };
  
  // Load the widget script
  (function() {
    const script = document.createElement('script');
    script.src = window.MIGRAINE_CHATBOT_CONFIG.baseUrl + '/widget.js';
    script.async = true;
    document.body.appendChild(script);
  })();
</script>
```

## Production Deployment

For production deployment, use Docker Compose:

1. **Build and start all services**:
   ```bash
   docker-compose up -d
   ```

2. **View logs**:
   ```bash
   docker-compose logs -f
   ```

3. **Stop all services**:
   ```bash
   docker-compose down
   ```

4. **Update your embed script** with your production URLs:
   ```html
   <script>
     window.MIGRAINE_CHATBOT_CONFIG = {
       baseUrl: 'https://your-production-frontend-url.com',
       apiUrl: 'https://your-production-backend-url.com',
       primaryColor: '#5762d5'
     };
     
     (function() {
       const script = document.createElement('script');
       script.src = window.MIGRAINE_CHATBOT_CONFIG.baseUrl + '/widget.js';
       script.async = true;
       document.body.appendChild(script);
     })();
   </script>
   ```

## Troubleshooting

1. **Backend API not responding**:
   - Verify the backend is running on http://localhost:8013
   - Check the console for CORS errors (you may need to update the allowed origins in main.py)

2. **Widget not showing on your site**:
   - Check that the `widget.js` file is being loaded correctly
   - Ensure your MIGRAINE_CHATBOT_CONFIG has the correct URLs

3. **Frontend can't connect to backend**:
   - Make sure the apiUrl in your configuration points to the correct backend address
   - Check for network errors in your browser's developer console

4. **No search results**:
   - Verify your OpenAI API key is valid
   - Check if Qdrant is running and has content indexed

## API Documentation

Access the interactive API documentation at http://localhost:8013/docs when the backend is running. 