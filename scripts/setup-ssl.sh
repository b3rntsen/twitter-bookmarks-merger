#!/bin/bash
# Script to set up SSL certificates using Let's Encrypt
# Run this on the EC2 instance after DNS is configured

set -e

DOMAIN1="twitter.vibe.dethele.com"
DOMAIN2="twitter.dethele.com"
EMAIL="${CERTBOT_EMAIL:-your-email@example.com}"  # Set CERTBOT_EMAIL env var or edit this

echo "🔒 Setting up SSL certificates for $DOMAIN1 and $DOMAIN2"
echo "📧 Using email: $EMAIL"
echo ""

# Check if domains resolve
echo "Checking DNS resolution..."
if ! nslookup $DOMAIN1 > /dev/null 2>&1; then
    echo "⚠️  Warning: $DOMAIN1 does not resolve. Make sure DNS is configured."
fi
if ! nslookup $DOMAIN2 > /dev/null 2>&1; then
    echo "⚠️  Warning: $DOMAIN2 does not resolve. Make sure DNS is configured."
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

# Get certificates for both domains
# Override entrypoint to run certbot directly (not the renewal loop)
echo ""
echo "Requesting certificate for $DOMAIN1..."
docker compose -f docker-compose.prod.yml run --rm --entrypoint="" certbot sh -c "certbot certonly --webroot --webroot-path=/var/www/certbot --email $EMAIL --agree-tos --no-eff-email -d $DOMAIN1"

echo ""
echo "Requesting certificate for $DOMAIN2..."
docker compose -f docker-compose.prod.yml run --rm --entrypoint="" certbot sh -c "certbot certonly --webroot --webroot-path=/var/www/certbot --email $EMAIL --agree-tos --no-eff-email -d $DOMAIN2"

echo ""
echo "✅ Certificates obtained successfully!"
echo ""
echo "Next steps:"
echo "1. Update .env file:"
echo "   USE_HTTPS=True"
echo ""
echo "2. Restart the application:"
echo "   docker compose -f docker-compose.prod.yml down"
echo "   docker compose -f docker-compose.prod.yml up -d"
echo ""
echo "3. Test HTTPS:"
echo "   curl https://$DOMAIN1"
echo "   curl https://$DOMAIN2"

