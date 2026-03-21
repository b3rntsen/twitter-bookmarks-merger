#!/bin/bash
# Script to set up SSL certificates using Let's Encrypt
# Run this on the EC2 instance after DNS is configured

set -e

DOMAIN="twitter.dethele.com"
EMAIL="${CERTBOT_EMAIL:-nikolaj@dethele.com}"

echo "🔒 Setting up SSL certificate for $DOMAIN"
echo "📧 Using email: $EMAIL"
echo ""

# Check if domain resolves
echo "Checking DNS resolution..."
if ! nslookup $DOMAIN > /dev/null 2>&1; then
    echo "⚠️  Warning: $DOMAIN does not resolve. Make sure DNS is configured."
fi

# Make sure nginx is running (for HTTP-01 challenge)
echo "Starting nginx container (if not running)..."
cd /home/ec2-user/twitter-bookmarks
docker compose -f docker-compose.prod.yml up -d nginx

# Wait a moment for nginx to start
sleep 5

# Ensure certbot volume directory exists in nginx container
echo "Ensuring certbot webroot directory exists..."
docker compose -f docker-compose.prod.yml exec nginx mkdir -p /var/www/certbot 2>/dev/null || true

# Get certificate
# Override entrypoint to run certbot directly (not the renewal loop)
echo ""
echo "Requesting certificate for $DOMAIN..."
docker compose -f docker-compose.prod.yml run --rm --entrypoint="" certbot sh -c "certbot certonly --webroot --webroot-path=/var/www/certbot --email $EMAIL --agree-tos --no-eff-email -d $DOMAIN"

echo ""
echo "✅ Certificate obtained successfully!"
echo ""
echo "Next steps:"
echo "1. Restart the application:"
echo "   docker compose -f docker-compose.prod.yml down"
echo "   docker compose -f docker-compose.prod.yml up -d"
echo ""
echo "2. Test HTTPS:"
echo "   curl https://$DOMAIN"

