#!/bin/bash
set -e

# Update system
sudo yum update -y

# Install Docker
sudo yum install -y docker
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker ec2-user

# Install Docker Compose (v2 as plugin)
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Also install as standalone binary for compatibility
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Install Git (if not already installed)
sudo yum install -y git

# Install Redis for Django-Q job queue
sudo yum install -y redis
sudo systemctl enable redis
sudo systemctl start redis

# Configure Redis
sudo sed -i 's/^# maxmemory <bytes>/maxmemory 512mb/' /etc/redis.conf
sudo sed -i 's/^# maxmemory-policy noeviction/maxmemory-policy allkeys-lru/' /etc/redis.conf
sudo systemctl restart redis

# Verify Redis is running
redis-cli ping || echo "Warning: Redis may not be running"

# Create application directory with proper permissions
APP_DIR="/home/ec2-user/${project_name}"
mkdir -p $APP_DIR
chown ec2-user:ec2-user $APP_DIR
chmod 755 $APP_DIR
cd $APP_DIR

# Create a startup script
cat > $APP_DIR/start.sh << 'EOFSTART'
#!/bin/bash
cd /home/ec2-user/twitter-bookmarks
docker-compose -f docker-compose.prod.yml up -d --build
EOFSTART

chmod +x $APP_DIR/start.sh

# Create a stop script
cat > $APP_DIR/stop.sh << 'EOFSTOP'
#!/bin/bash
cd /home/ec2-user/twitter-bookmarks
docker-compose -f docker-compose.prod.yml down
EOFSTOP

chmod +x $APP_DIR/stop.sh

# Create a logs script
cat > $APP_DIR/logs.sh << 'EOFLOGS'
#!/bin/bash
cd /home/ec2-user/twitter-bookmarks
docker-compose -f docker-compose.prod.yml logs -f
EOFLOGS

chmod +x $APP_DIR/logs.sh

# Log completion
echo "Docker and Docker Compose installed successfully" >> /var/log/user-data.log
echo "Application directory created at $APP_DIR" >> /var/log/user-data.log
echo "Next steps:" >> /var/log/user-data.log
echo "1. Upload your application code to $APP_DIR" >> /var/log/user-data.log
echo "2. Upload your .env file" >> /var/log/user-data.log
echo "3. Run: cd $APP_DIR && ./start.sh" >> /var/log/user-data.log

