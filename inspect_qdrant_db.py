#!/usr/bin/env python3
"""
Utility script to inspect Qdrant database contents and statistics
"""

import os
import sys
import argparse
import json
import urllib.request
import urllib.error
from dotenv import load_dotenv
from tabulate import tabulate
from qdrant_client import QdrantClient
from qdrant_client.http.models import Filter, FieldCondition, MatchValue
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("qdrant-inspector")

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Inspect Qdrant database contents")
    parser.add_argument('--host', help='Qdrant host', default=None)
    parser.add_argument('--port', help='Qdrant port', type=int, default=None)
    parser.add_argument('--collection', help='Collection name', default=None)
    parser.add_argument('--search', help='Search for a specific term', default=None)
    parser.add_argument('--limit', help='Limit number of results', type=int, default=10)
    parser.add_argument('--stats', help='Show collection statistics', action='store_true')
    parser.add_argument('--wp', help='Filter by WordPress content', action='store_true')
    parser.add_argument('--external', help='Filter by external content', action='store_true')
    parser.add_argument('--show-content', help='Show full content in results', action='store_true')
    args = parser.parse_args()

    # Load environment variables from .env
    load_dotenv('./backend/.env')
    
    # Connect to Qdrant
    qdrant_host = args.host or os.getenv("QDRANT_HOST", "localhost")
    qdrant_port = args.port or int(os.getenv("QDRANT_PORT", 6333))
    collection_name = args.collection or os.getenv("COLLECTION_NAME", "migraine_content")
    base_url = f"http://{qdrant_host}:{qdrant_port}"
    
    print(f"\n🔍 Connecting to Qdrant at {qdrant_host}:{qdrant_port}, collection: {collection_name}\n")
    
    try:
        # Create Qdrant client
        client = QdrantClient(host=qdrant_host, port=qdrant_port)
        
        # Get collection information using direct HTTP request to avoid compatibility issues
        try:
            collection_info = make_request(f"{base_url}/collections/{collection_name}")
            collection_info = json.loads(collection_info)
            
            print(f"✅ Connected to collection: {collection_name}")
            
            if args.stats:
                print_collection_stats(base_url, collection_name, collection_info)
                
            # Count points by type
            count_wp = count_points_by_type(client, collection_name, "migraine_ie")
            count_external = count_points_by_type(client, collection_name, "external")
            
            print(f"\n📊 Content Statistics:")
            print(f"  - WordPress content: {count_wp} points")
            print(f"  - External content: {count_external} points")
            print(f"  - Total: {count_wp + count_external} points")
            
            # Search or scroll through points
            if args.search:
                search_points(client, collection_name, args.search, args.limit, args.wp, args.external, args.show_content)
            else:
                list_points(client, collection_name, args.limit, args.wp, args.external, args.show_content)
                
        except Exception as e:
            print(f"❌ Error accessing collection: {e}")
            print(f"\nAvailable collections:")
            collections_response = make_request(f"{base_url}/collections")
            collections_data = json.loads(collections_response)
            for c in collections_data.get('result', {}).get('collections', []):
                print(f"  - {c.get('name')}")
            return 1
            
    except Exception as e:
        print(f"❌ Error connecting to Qdrant: {e}")
        return 1
        
    return 0

def make_request(url, method="GET", data=None):
    """Make HTTP request to Qdrant server"""
    headers = {"Content-Type": "application/json"}
    
    if data:
        data = data.encode('utf-8')
    
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req) as response:
            return response.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP Error: {e.code} - {e.reason}")
        print(e.read().decode('utf-8'))
        raise
    except urllib.error.URLError as e:
        print(f"❌ URL Error: {e.reason}")
        raise

def print_collection_stats(base_url, collection_name, collection_info):
    """Print detailed collection statistics using direct HTTP requests"""
    print(f"\n📈 Collection Statistics:")
    
    # Extract information from collection_info response
    config = collection_info.get('result', {})
    
    vector_size = config.get('config', {}).get('params', {}).get('vectors', {}).get('size', 'Unknown')
    vector_distance = config.get('config', {}).get('params', {}).get('vectors', {}).get('distance', 'Unknown')
    points_count = config.get('points_count', 'Unknown')
    
    print(f"  - Vectors dimension: {vector_size}")
    print(f"  - Distance: {vector_distance}")
    print(f"  - Total points: {points_count}")
    
    # Get collection indexes using direct HTTP request
    try:
        indexes_response = make_request(f"{base_url}/collections/{collection_name}/index")
        indexes_data = json.loads(indexes_response)
        
        if indexes_data and indexes_data.get('result', {}).get('payload_schema', {}):
            print(f"\n  - Payload Indexes:")
            for field_name, schema in indexes_data.get('result', {}).get('payload_schema', {}).items():
                print(f"    • {field_name} ({schema.get('type', 'unknown')})")
    except Exception as e:
        logger.error(f"Error getting indexes: {e}")

def count_points_by_type(client, collection_name, source_type):
    """Count points by source type"""
    try:
        count = client.count(
            collection_name=collection_name,
            count_filter=Filter(
                must=[
                    FieldCondition(
                        key="source_type",
                        match=MatchValue(value=source_type)
                    )
                ]
            )
        )
        return count.count
    except Exception as e:
        logger.error(f"Error counting points: {e}")
        return 0

def list_points(client, collection_name, limit, wp_only=False, external_only=False, show_content=False):
    """List points in the collection"""
    print(f"\n📝 Listing points (limit: {limit}):")
    
    # Create filter based on options
    scroll_filter = None
    if wp_only:
        scroll_filter = Filter(
            must=[FieldCondition(key="source_type", match=MatchValue(value="migraine_ie"))]
        )
    elif external_only:
        scroll_filter = Filter(
            must=[FieldCondition(key="source_type", match=MatchValue(value="external"))]
        )
    
    # Fetch points
    try:
        results = client.scroll(
            collection_name=collection_name,
            limit=limit,
            with_payload=True,
            with_vectors=False,
            scroll_filter=scroll_filter
        )[0]
        
        # Format and display results
        display_results(results, show_content)
        
    except Exception as e:
        print(f"❌ Error listing points: {e}")

def search_points(client, collection_name, search_term, limit, wp_only=False, external_only=False, show_content=False):
    """Search for points containing the search term"""
    print(f"\n🔎 Searching for '{search_term}' (limit: {limit}):")
    
    # Create payload filter
    payload_filter = None
    if wp_only:
        payload_filter = Filter(
            must=[FieldCondition(key="source_type", match=MatchValue(value="migraine_ie"))]
        )
    elif external_only:
        payload_filter = Filter(
            must=[FieldCondition(key="source_type", match=MatchValue(value="external"))]
        )
    
    # For proper searching, we'd use query vectors, but for basic inspection
    # we'll simply filter points that have the search term in their content
    try:
        results = client.scroll(
            collection_name=collection_name,
            limit=limit * 10,  # Get more results to filter
            with_payload=True,
            with_vectors=False,
            scroll_filter=payload_filter
        )[0]
        
        # Filter results that contain the search term
        filtered_results = []
        for point in results:
            if search_term.lower() in str(point.payload.get('content', '')).lower() or \
               search_term.lower() in str(point.payload.get('title', '')).lower():
                filtered_results.append(point)
                if len(filtered_results) >= limit:
                    break
        
        # Display results
        if filtered_results:
            display_results(filtered_results, show_content)
        else:
            print("No matching results found.")
        
    except Exception as e:
        print(f"❌ Error searching points: {e}")

def display_results(results, show_content=False):
    """Format and display results in a table"""
    if not results:
        print("No results found.")
        return
        
    # Prepare table data
    table_data = []
    for i, point in enumerate(results, 1):
        # Extract fields, handling missing fields gracefully
        point_id = point.id
        title = point.payload.get('title', 'No title')
        source = point.payload.get('source', 'Unknown')
        source_type = point.payload.get('source_type', 'Unknown')
        url = point.payload.get('url', 'No URL')
        
        # Format content
        content = point.payload.get('content', 'No content')
        if not show_content:
            content = content[:100] + "..." if len(content) > 100 else content
        
        # Add to table
        table_data.append([
            i, point_id, title, source, source_type, url, 
            content if show_content else content.replace('\n', ' ')
        ])
    
    # Display table
    headers = ["#", "ID", "Title", "Source", "Type", "URL", "Content"]
    print(tabulate(table_data, headers=headers, tablefmt="pretty"))
    print(f"\nTotal: {len(results)} results")

if __name__ == "__main__":
    # Check if tabulate is installed
    try:
        import tabulate
    except ImportError:
        print("Installing required packages...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "tabulate"])
        
    sys.exit(main()) 