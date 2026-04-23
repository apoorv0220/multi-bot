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
        default_port = os.getenv("BACKEND_PORT") or os.getenv("API_PORT", "8043")
        self.api_url = api_url or f"http://localhost:{default_port}"
        
    async def start_reindex(self, tenant_id: str = None):
        """Start a new reindexing job"""
        async with aiohttp.ClientSession() as session:
            data = {"tenant_id": tenant_id} if tenant_id else {}
            
            try:
                async with session.post(f"{self.api_url}/api/reindex", json=data) as response:
                    if response.status == 200:
                        result = await response.json()
                        print(f"✅ Reindexing job started successfully!")
                        print(f"   Job ID: {result['job_id']}")
                        print(f"   Status: {result['status']}")
                        print(f"   Message: {result.get('status', 'started')}")
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
        jobs_data = await self.list_jobs(return_data=True)
        if not jobs_data:
            return None
        jobs = jobs_data.get("jobs", [])
        if not jobs:
            print("No jobs found")
            return None
        target = next((j for j in jobs if j["id"] == job_id), jobs[0] if not job_id else None)
        if not target:
            print(f"❌ Job not found: {job_id}")
            return None
        self._print_status(target)
        return target

    async def list_jobs(self, return_data: bool = False):
        """List all reindexing jobs"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"{self.api_url}/api/reindex/jobs") as response:
                    if response.status == 200:
                        jobs = await response.json()
                        result = {
                            "jobs": jobs,
                            "total_jobs": len(jobs),
                            "active_jobs": len([j for j in jobs if j.get("status") == "running"]),
                        }
                        if not return_data:
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
        """Cancellation is not supported in the current API"""
        print("❌ Cancel is not supported by current API version.")
        return None

    async def monitor(self, job_id: str = None, interval: int = 5):
        """Monitor reindexing progress in real-time"""
        print(f"🔍 Monitoring reindexing progress (updates every {interval}s)")
        print("Press Ctrl+C to stop monitoring\n")
        
        try:
            while True:
                status = await self.get_status(job_id)
                if status and status.get('status') in ['completed', 'failed']:
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
        print(f"   Message: {status.get('error') or 'Running'}")
        
        if status.get('started_at'):
            print(f"   Start Time: {status['started_at']}")
        
        if status.get('created_at'):
            print(f"   Created: {status['created_at']}")
        
        progress = status.get('meta', {}).get('progress')
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
            print(f"   Start: {job.get('started_at', 'N/A')}")
            
            progress = job.get("meta", {}).get("progress", {})
            if progress:
                print(f"   Progress: {progress.get('progress_percentage', 0):.1f}%")
            print(f"   Message: {job.get('error') or 'Running'}")
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
    parser.add_argument("--api-url", help="API URL (default: http://localhost:${BACKEND_PORT or API_PORT})")
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Start command
    start_parser = subparsers.add_parser('start', help='Start reindexing')
    start_parser.add_argument('--tenant-id', help='Target tenant id (superadmin only)')
    
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
        await manager.start_reindex(tenant_id=args.tenant_id)
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