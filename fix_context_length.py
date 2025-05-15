#!/usr/bin/env python3
"""
Simple script to fix context length issues in Qdrant database using direct HTTP requests
"""

import os
import sys
import json
import urllib.request
import urllib.error
import argparse
from dotenv import load_dotenv

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Fix context length issues in Qdrant database")
    parser.add_argument('--host', help='Qdrant host', default=None)
    parser.add_argument('--port', help='Qdrant port', type=int, default=None)
    parser.add_argument('--collection', help='Collection name', default=None)
    parser.add_argument('--limit', help='Max content length in chars', type=int, default=8000)
    parser.add_argument('--dry-run', help='Only show what would change without modifying', action='store_true')
    parser.add_argument('--only-external', help='Only check external content', action='store_true')
    args = parser.parse_args()

    # Load environment variables
    load_dotenv('./backend/.env')
    
    # Set up connection parameters
    qdrant_host = args.host or os.getenv("QDRANT_HOST", "localhost")
    qdrant_port = args.port or int(os.getenv("QDRANT_PORT", 6333))
    collection_name = args.collection or os.getenv("COLLECTION_NAME", "migraine_content")
    base_url = f"http://{qdrant_host}:{qdrant_port}"
    
    print(f"\n🔍 Connecting to Qdrant at {base_url}, collection: {collection_name}\n")
    
    try:
        # Check if collection exists
        response = make_request(f"{base_url}/collections")
        collections = json.loads(response)
        collection_names = [c['name'] for c in collections['result']['collections']]
        
        if collection_name not in collection_names:
            print(f"❌ Collection '{collection_name}' not found. Available collections: {', '.join(collection_names)}")
            return 1
        
        print(f"✅ Collection '{collection_name}' found")
        
        # Get and check points with large content
        large_points = []
        
        # We'll use scroll API to get points
        offset = None
        limit = 20  # Batch size
        total_points = 0
        
        while True:
            # Prepare scroll request
            scroll_data = {
                "limit": limit,
                "with_payload": True,
                "with_vectors": False
            }
            
            # Add filter for external content if requested
            if args.only_external:
                scroll_data["filter"] = {
                    "must": [
                        {
                            "key": "source_type",
                            "match": {
                                "value": "external"
                            }
                        }
                    ]
                }
            
            # Add offset if we have one
            if offset:
                scroll_data["offset"] = offset
            
            # Make request
            response = make_request(
                f"{base_url}/collections/{collection_name}/points/scroll", 
                method="POST",
                data=json.dumps(scroll_data)
            )
            result = json.loads(response)
            
            points = result['result']['points']
            next_offset = result['result'].get('next_page_offset')
            
            # Process this batch
            for point in points:
                total_points += 1
                content = point['payload'].get('content', '')
                
                if content and len(content) > args.limit:
                    source = point['payload'].get('source', 'Unknown')
                    url = point['payload'].get('url', 'No URL')
                    title = point['payload'].get('title', 'No title')
                    
                    large_points.append({
                        'id': point['id'],
                        'title': title,
                        'source': source,
                        'url': url,
                        'content_length': len(content),
                        'content': content,
                        'payload': point['payload']
                    })
                    
                    print(f"Found large content: ID={point['id']}, Title={title[:50]}..., Length={len(content)}")
            
            # Break if no more results
            if not next_offset or not points:
                break
                
            offset = next_offset
        
        print(f"\nChecked {total_points} total points")
        
        if not large_points:
            print("✅ No points with excessively large content found!")
            return 0
        
        print(f"⚠️ Found {len(large_points)} points with content larger than {args.limit} characters")
        
        if args.dry_run:
            print("Dry run mode - not modifying anything")
            return 0
        
        # Fix the large content
        for i, point in enumerate(large_points, 1):
            # Truncate content
            truncated_content = truncate_content(point['content'], args.limit)
            
            # Update payload
            updated_payload = point['payload'].copy()
            updated_payload['content'] = truncated_content
            
            # Prepare update request
            update_data = {
                "points": [
                    {
                        "id": point['id'],
                        "payload": updated_payload
                    }
                ]
            }
            
            # Make update request
            make_request(
                f"{base_url}/collections/{collection_name}/points",
                method="PUT",
                data=json.dumps(update_data)
            )
            
            print(f"Fixed point {i}/{len(large_points)}: {point['title'][:30]}...")
        
        print(f"\n✅ Successfully fixed {len(large_points)} points with large content")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1
    
    return 0

def truncate_content(text, max_chars):
    """Truncate text to fit within max chars, preserving beginning and end"""
    if len(text) <= max_chars:
        return text
    
    # Take 80% from beginning, 20% from end
    begin_portion = int(max_chars * 0.8)
    end_portion = max_chars - begin_portion
    return text[:begin_portion] + "\n...[content truncated]...\n" + text[-end_portion:]

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

if __name__ == "__main__":
    sys.exit(main()) 