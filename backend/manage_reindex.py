#!/usr/bin/env python3
"""
Management script for MRN Web Designs reindexing operations.
This script provides command-line interface to monitor and control reindexing jobs.
"""

import asyncio
import sys
import argparse
import json
from datetime import datetime
import aiohttp
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class ReindexManager:
    def __init__(self, api_url: str = None):
        self.api_url = api_url or f"http://localhost:{os.getenv('API_PORT', 8043)}"
        
    async def start_reindex(self, force_restart: bool = False, chunk_size: int = None, batch_size: int = None):
        """Start a new reindexing job"""
        async with aiohttp.ClientSession() as session:
            data = {
                "force_restart": force_restart,
                "chunk_size": chunk_size,
                "batch_size": batch_size
            }
            # Remove None values
            data = {k: v for k, v in data.items() if v is not None}
            
            try:
                async with session.post(f"{self.api_url}/api/reindex", json=data) as response:
                    if response.status == 200:
                        result = await response.json()
                        print(f"✅ Reindexing job started successfully!")
                        print(f"   Job ID: {result['job_id']}")
                        print(f"   Status: {result['status']}")
                        print(f"   Estimated Duration: {result.get('estimated_duration', 'Unknown')}")
                        print(f"   Message: {result['message']}")
                        return result['job_id']
                    else:
                        error = await response.json()
                        print(f"❌ Failed to start reindexing: {error.get('detail', 'Unknown error')}")
                        return None
            except Exception as e:
                print(f"❌ Error connecting to API: {e}")
                return None

    async def get_status(self, job_id: str = None):
        """Get status of reindexing jobs"""
        async with aiohttp.ClientSession() as session:
            url = f"{self.api_url}/api/reindex/status"
            if job_id:
                url += f"?job_id={job_id}"
                
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        result = await response.json()
                        self._print_status(result)
                        return result
                    else:
                        error = await response.json()
                        print(f"❌ Failed to get status: {error.get('detail', 'Unknown error')}")
                        return None
            except Exception as e:
                print(f"❌ Error connecting to API: {e}")
                return None

    async def list_jobs(self):
        """List all reindexing jobs"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"{self.api_url}/api/reindex/jobs") as response:
                    if response.status == 200:
                        result = await response.json()
                        self._print_jobs_list(result)
                        return result
                    else:
                        error = await response.json()
                        print(f"❌ Failed to list jobs: {error.get('detail', 'Unknown error')}")
                        return None
            except Exception as e:
                print(f"❌ Error connecting to API: {e}")
                return None

    async def cancel_job(self, job_id: str):
        """Cancel a specific reindexing job"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.delete(f"{self.api_url}/api/reindex/jobs/{job_id}") as response:
                    if response.status == 200:
                        result = await response.json()
                        print(f"✅ Job cancellation requested")
                        print(f"   Job ID: {result['job_id']}")
                        print(f"   Status: {result['status']}")
                        print(f"   Message: {result['message']}")
                        return result
                    else:
                        error = await response.json()
                        print(f"❌ Failed to cancel job: {error.get('detail', 'Unknown error')}")
                        return None
            except Exception as e:
                print(f"❌ Error connecting to API: {e}")
                return None

    async def monitor(self, job_id: str = None, interval: int = 5):
        """Monitor reindexing progress in real-time"""
        print(f"🔍 Monitoring reindexing progress (updates every {interval}s)")
        print("Press Ctrl+C to stop monitoring\n")
        
        try:
            while True:
                status = await self.get_status(job_id)
                if status and status.get('status') in ['completed', 'failed', 'cancelled']:
                    print(f"\n🏁 Job finished with status: {status['status']}")
                    break
                
                print(f"⏱️  Next update in {interval} seconds...")
                await asyncio.sleep(interval)
                print("\033[H\033[J")  # Clear screen
                
        except KeyboardInterrupt:
            print("\n👋 Monitoring stopped")

    def _print_status(self, status):
        """Print formatted status information"""
        print(f"📊 Reindexing Status")
        print(f"   Job ID: {status.get('job_id', 'N/A')}")
        print(f"   Status: {self._format_status(status['status'])}")
        print(f"   Message: {status['message']}")
        
        if status.get('start_time'):
            print(f"   Start Time: {status['start_time']}")
        
        if status.get('elapsed_time'):
            elapsed = status['elapsed_time']
            print(f"   Elapsed Time: {self._format_duration(elapsed)}")
        
        progress = status.get('progress')
        if progress:
            print(f"\n📈 Progress Details:")
            print(f"   Total Items: {progress['total_items']}")
            print(f"   Processed: {progress['processed_items']}")
            print(f"   Failed: {progress['failed_items']}")
            print(f"   Progress: {progress['progress_percentage']:.1f}%")
            print(f"   Current Batch: {progress['current_batch']}")
            
            if progress['total_items'] > 0:
                # Simple progress bar
                bar_length = 40
                filled_length = int(bar_length * progress['progress_percentage'] / 100)
                bar = '█' * filled_length + '░' * (bar_length - filled_length)
                print(f"   [{bar}] {progress['progress_percentage']:.1f}%")

    def _print_jobs_list(self, jobs_data):
        """Print formatted jobs list"""
        jobs = jobs_data.get('jobs', [])
        print(f"📋 Reindexing Jobs ({jobs_data['total_jobs']} total, {jobs_data['active_jobs']} active)")
        print()
        
        if not jobs:
            print("   No jobs found")
            return
        
        for job in jobs:
            status_icon = self._get_status_icon(job['status'])
            print(f"{status_icon} {job['job_id']}")
            print(f"   Status: {self._format_status(job['status'])}")
            print(f"   Start: {job.get('start_time', 'N/A')}")
            
            if job.get('elapsed_time'):
                print(f"   Duration: {self._format_duration(job['elapsed_time'])}")
            
            print(f"   Message: {job['message']}")
            print()

    def _format_status(self, status):
        """Format status with colors/emojis"""
        status_map = {
            'idle': '💤 Idle',
            'starting': '🚀 Starting',
            'running': '⚡ Running',
            'completed': '✅ Completed',
            'failed': '❌ Failed',
            'cancelled': '🚫 Cancelled'
        }
        return status_map.get(status, f"❓ {status}")

    def _get_status_icon(self, status):
        """Get icon for status"""
        icons = {
            'idle': '💤',
            'starting': '🚀',
            'running': '⚡',
            'completed': '✅',
            'failed': '❌',
            'cancelled': '🚫'
        }
        return icons.get(status, '❓')

    def _format_duration(self, seconds):
        """Format duration in human-readable format"""
        if seconds < 60:
            return f"{seconds:.1f}s"
        elif seconds < 3600:
            minutes = seconds / 60
            return f"{minutes:.1f}m"
        else:
            hours = seconds / 3600
            return f"{hours:.1f}h"

async def main():
    parser = argparse.ArgumentParser(description="MRN Web Designs Reindexing Manager")
    parser.add_argument("--api-url", help="API URL (default: http://localhost:8043)")
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Start command
    start_parser = subparsers.add_parser('start', help='Start reindexing')
    start_parser.add_argument('--force-restart', action='store_true', help='Force restart if job already running')
    start_parser.add_argument('--chunk-size', type=int, help='Items per chunk (default: 50)')
    start_parser.add_argument('--batch-size', type=int, help='Concurrent processing batch size (default: 10)')
    
    # Status command
    status_parser = subparsers.add_parser('status', help='Get reindexing status')
    status_parser.add_argument('--job-id', help='Specific job ID to check')
    
    # List command
    subparsers.add_parser('list', help='List all reindexing jobs')
    
    # Cancel command
    cancel_parser = subparsers.add_parser('cancel', help='Cancel reindexing job')
    cancel_parser.add_argument('job_id', help='Job ID to cancel')
    
    # Monitor command
    monitor_parser = subparsers.add_parser('monitor', help='Monitor reindexing progress')
    monitor_parser.add_argument('--job-id', help='Specific job ID to monitor')
    monitor_parser.add_argument('--interval', type=int, default=5, help='Update interval in seconds (default: 5)')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    manager = ReindexManager(args.api_url)
    
    if args.command == 'start':
        await manager.start_reindex(
            force_restart=args.force_restart,
            chunk_size=args.chunk_size,
            batch_size=args.batch_size
        )
    elif args.command == 'status':
        await manager.get_status(args.job_id)
    elif args.command == 'list':
        await manager.list_jobs()
    elif args.command == 'cancel':
        await manager.cancel_job(args.job_id)
    elif args.command == 'monitor':
        await manager.monitor(args.job_id, args.interval)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
        sys.exit(0) 