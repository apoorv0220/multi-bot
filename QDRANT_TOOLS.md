# Qdrant Database Management Tools

This document describes the tools available for managing and inspecting the Qdrant vector database used in the Migraine.ie AI Chatbot.

## 1. Database Connection Testing

The `test_qdrant_connection.py` script is used to verify that your Qdrant database is accessible and functioning correctly.

```bash
# Basic test
./test_qdrant_connection.py

# With custom host/port
./test_qdrant_connection.py --host localhost --port 6333
```

This tool:
- Checks if the Qdrant server is accessible
- Creates a test collection
- Inserts a test point
- Performs a search
- Cleans up by deleting the test collection

## 2. Inspecting Database Contents

The `inspect_qdrant_db.py` script allows you to explore the contents of your Qdrant database.

```bash
# Basic usage - show 10 points
./inspect_qdrant_db.py

# Show detailed statistics
./inspect_qdrant_db.py --stats

# Show only WordPress content
./inspect_qdrant_db.py --wp

# Show only external content
./inspect_qdrant_db.py --external

# Search for specific content
./inspect_qdrant_db.py --search "migraine"

# Show more results
./inspect_qdrant_db.py --limit 20

# Show full content text
./inspect_qdrant_db.py --show-content
```

This tool helps you:
- Verify that content has been properly indexed
- Check the distribution of WordPress vs external content
- Search for specific content within the database
- Examine the details of indexed documents

## 3. Fixing Large Content Issues

The `fix_large_content.py` script helps identify and fix content that's too large for the OpenAI API context window.

```bash
# Identify large content (dry run mode)
./fix_large_content.py --dry-run

# Fix large content by truncating it
./fix_large_content.py

# Only check/fix external content
./fix_large_content.py --only-external

# Set custom content length limit
./fix_large_content.py --limit 10000
```

This tool:
- Identifies points with excessively large content
- Truncates large content while preserving important parts
- Updates the database with truncated content
- Prevents "context length exceeded" errors when querying OpenAI

## 4. Docker Container Management

The following scripts help manage the Qdrant Docker container:

```bash
# Start Qdrant container
./start_qdrant_docker.sh

# Stop Qdrant container
./stop_qdrant_docker.sh
```

## 5. Full System Startup

The `start_migraine_chatbot.sh` script starts the entire system, including the Qdrant database and backend API.

```bash
./start_migraine_chatbot.sh
```

## Troubleshooting

If you encounter a "context length exceeded" error when searching:

1. First identify which documents might be causing the issue:
   ```bash
   ./inspect_qdrant_db.py --search "your search term" --show-content
   ```

2. Then run the content fixer to truncate large documents:
   ```bash
   ./fix_large_content.py
   ```

3. Restart the backend API to apply the changes.

## Database Location

The Qdrant database files are stored in the `qdrant_data` directory at the root of the project. This directory is mounted as a volume in the Docker container, ensuring data persistence between container restarts. 