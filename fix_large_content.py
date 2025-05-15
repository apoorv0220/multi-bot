#!/usr/bin/env python3
"""
Utility script to identify and fix large content in the Qdrant database
"""

import os
import sys
import uuid
import asyncio
import argparse
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http.models import Filter, FieldCondition, MatchValue, PointStruct
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("content-fixer")

# Max content length in characters
MAX_CONTENT_LENGTH = 8000

async def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Identify and fix large content in Qdrant")
    parser.add_argument('--host', help='Qdrant host', default=None)
    parser.add_argument('--port', help='Qdrant port', type=int, default=None)
    parser.add_argument('--collection', help='Collection name', default=None)
    parser.add_argument('--limit', help='Max content length in chars', type=int, default=MAX_CONTENT_LENGTH)
    parser.add_argument('--dry-run', help='Only show what would change without modifying', action='store_true')
    parser.add_argument('--only-external', help='Only check external content', action='store_true')
    args = parser.parse_args()

    # Load environment variables from .env
    load_dotenv('./backend/.env')
    
    # Connect to Qdrant
    qdrant_host = args.host or os.getenv("QDRANT_HOST", "localhost")
    qdrant_port = args.port or int(os.getenv("QDRANT_PORT", 6333))
    collection_name = args.collection or os.getenv("COLLECTION_NAME", "migraine_content")
    
    print(f"\n🔍 Connecting to Qdrant at {qdrant_host}:{qdrant_port}, collection: {collection_name}\n")
    
    try:
        # Create Qdrant client
        client = QdrantClient(host=qdrant_host, port=qdrant_port)
        
        # Get collection information
        try:
            collection_info = client.get_collection(collection_name=collection_name)
            print(f"✅ Connected to collection: {collection_name} with {collection_info.points_count} points")
            
            # Apply filter if needed
            filter_condition = None
            if args.only_external:
                filter_condition = Filter(
                    must=[FieldCondition(key="source_type", match=MatchValue(value="external"))]
                )
                print("Checking only external content...")
            
            # Get all points
            results = client.scroll(
                collection_name=collection_name,
                limit=10000,  # Large enough to get all points
                with_payload=True,
                with_vectors=True,
                scroll_filter=filter_condition
            )[0]
            
            print(f"Found {len(results)} points to check")
            
            # Identify points with large content
            large_content_points = []
            for point in results:
                content = point.payload.get('content', '')
                if len(content) > args.limit:
                    large_content_points.append(point)
            
            if not large_content_points:
                print("✅ No points with excessively large content found!")
                return 0
                
            print(f"⚠️ Found {len(large_content_points)} points with content larger than {args.limit} characters")
            
            if args.dry_run:
                print("Dry run mode - showing points with large content:")
                for point in large_content_points[:10]:  # Show first 10 as example
                    content_len = len(point.payload.get('content', ''))
                    url = point.payload.get('url', 'No URL')
                    title = point.payload.get('title', 'No title')
                    print(f"ID: {point.id}, Title: {title[:50]}..., URL: {url}, Content length: {content_len} chars")
                    
                if len(large_content_points) > 10:
                    print(f"...and {len(large_content_points) - 10} more")
                return 0
            
            # Fix large content points
            fixed_count = 0
            for point in large_content_points:
                await fix_point(client, collection_name, point, args.limit)
                fixed_count += 1
                if fixed_count % 10 == 0:
                    print(f"Fixed {fixed_count}/{len(large_content_points)} points...")
            
            print(f"✅ Successfully fixed {fixed_count} points with large content!")
                
        except Exception as e:
            print(f"❌ Error accessing collection: {e}")
            return 1
            
    except Exception as e:
        print(f"❌ Error connecting to Qdrant: {e}")
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

async def fix_point(client, collection_name, point, max_length):
    """Fix a point with large content"""
    try:
        content = point.payload.get('content', '')
        if len(content) <= max_length:
            return  # No need to fix
            
        # Create truncated content
        truncated_content = truncate_content(content, max_length)
        
        # Update payload with truncated content
        new_payload = point.payload.copy()
        new_payload['content'] = truncated_content
        
        # Create new point with same ID, vector but updated payload
        fixed_point = PointStruct(
            id=point.id,
            vector=point.vector,
            payload=new_payload
        )
        
        # Update the point in the database
        client.upsert(
            collection_name=collection_name,
            points=[fixed_point]
        )
        
    except Exception as e:
        logger.error(f"Error fixing point {point.id}: {e}")

if __name__ == "__main__":
    sys.exit(asyncio.run(main())) 