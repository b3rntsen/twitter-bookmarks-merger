#!/bin/bash
# Script to reload nginx after certificate renewal
# This can be called from certbot's deploy-hook or run manually

cd /home/ec2-user/twitter-bookmarks
docker compose -f docker-compose.prod.yml exec nginx nginx -s reload 2>/dev/null || \
docker compose -f docker-compose.prod.yml restart nginx

echo "Nginx reloaded after certificate renewal"
