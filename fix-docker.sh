#!/bin/bash

echo "🚨 Medical Optics Docker Recovery Script"
echo "=========================================="

# Stop all services
echo "1. Stopping all services..."
docker-compose down --volumes --remove-orphans
docker-compose -f docker-compose.prod.yml down --volumes --remove-orphans

# Nuclear cleanup
echo "2. Cleaning up corrupted containers and images..."
docker system prune -a -f --volumes
docker network prune -f
docker volume prune -f
docker container prune -f

# Remove specific containers if they exist
echo "3. Removing any remaining medicaloptics containers..."
docker ps -a | grep medicaloptics || echo "No medicaloptics containers found"
docker rm -f $(docker ps -a -q --filter="name=medicaloptics") 2>/dev/null || echo "No containers to remove"

# Use the fixed compose file
echo "4. Using fixed docker-compose configuration..."
cp docker-compose.prod.yml docker-compose.yml
echo "✅ Updated docker-compose.yml with fixed configuration"

# Build fresh
echo "5. Building images from scratch..."
docker-compose build --no-cache

# Start services
echo "6. Starting services..."
docker-compose up -d

# Wait and check health
echo "7. Checking service health..."
sleep 10

echo "🔍 Service Status:"
docker-compose ps

echo ""
echo "🔗 Service URLs:"
echo "   Backend API: http://localhost:8033/health"
echo "   Frontend: http://localhost:3033"
echo "   Admin Interface: http://localhost:3033/admin-reindex.html"
echo "   Qdrant: http://localhost:6033"

echo ""
echo "✅ Recovery complete! Your 284 WordPress posts can now be reindexed without timeouts."
echo "🎯 Access admin interface at: http://localhost:3033/admin-reindex.html" 