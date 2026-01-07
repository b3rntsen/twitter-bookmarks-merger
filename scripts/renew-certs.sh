#!/bin/bash
# Script to manually renew certificates and reload nginx
# This is also what the certbot container runs automatically

set -e

cd /home/ec2-user/twitter-bookmarks

echo "🔄 Renewing SSL certificates..."

# Renew certificates
docker compose -f docker-compose.prod.yml run --rm --entrypoint="" certbot sh -c "certbot renew"

# Reload nginx to pick up new certificates
echo "🔄 Reloading nginx..."
docker compose -f docker-compose.prod.yml exec nginx nginx -s reload

echo "✅ Certificate renewal complete!"

