#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TERRAFORM_DIR="$PROJECT_DIR/terraform"

echo -e "${GREEN}📤 Uploading application to AWS${NC}"
echo ""

# Check if Terraform state exists
if [ ! -f "$TERRAFORM_DIR/terraform.tfstate" ]; then
    echo -e "${RED}❌ Error: Terraform state not found. Please run ./scripts/deploy.sh first${NC}"
    exit 1
fi

# Get instance IP from Terraform
INSTANCE_IP=$(cd "$TERRAFORM_DIR" && terraform output -raw instance_public_ip 2>/dev/null || echo "")

if [ -z "$INSTANCE_IP" ]; then
    echo -e "${RED}❌ Error: Could not get instance IP from Terraform${NC}"
    exit 1
fi

echo "Instance IP: $INSTANCE_IP"
echo ""

# Check if .env file exists
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo -e "${YELLOW}⚠️  Warning: .env file not found${NC}"
    echo "You'll need to create it on the server manually"
fi

# Find SSH key
SSH_KEY=""
if [ -n "$SSH_KEY_PATH" ]; then
    SSH_KEY="$SSH_KEY_PATH"
elif [ -f ~/.ssh/twitter-bookmarks-key.pem ]; then
    SSH_KEY=~/.ssh/twitter-bookmarks-key.pem
else
    # Try to find any .pem file
    SSH_KEY=$(ls ~/.ssh/*.pem 2>/dev/null | head -n 1)
fi

if [ -z "$SSH_KEY" ] || [ ! -f "$SSH_KEY" ]; then
    echo -e "${RED}❌ Error: SSH key not found${NC}"
    echo ""
    echo "Please either:"
    echo "1. Set SSH_KEY_PATH environment variable: export SSH_KEY_PATH=~/.ssh/your-key.pem"
    echo "2. Place your key at ~/.ssh/twitter-bookmarks-key.pem"
    echo "3. Or have any .pem file in ~/.ssh/"
    exit 1
fi

echo "Using SSH key: $SSH_KEY"
chmod 400 "$SSH_KEY" 2>/dev/null || true

# Check if rsync is available on server, install if not
echo -e "${YELLOW}Checking for rsync on server...${NC}"
if ! ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ec2-user@$INSTANCE_IP "command -v rsync &> /dev/null"; then
    echo -e "${YELLOW}Installing rsync on server...${NC}"
    ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ec2-user@$INSTANCE_IP << 'ENDSSH'
        if command -v yum &> /dev/null; then
            sudo yum install -y rsync
        elif command -v apt-get &> /dev/null; then
            sudo apt-get update && sudo apt-get install -y rsync
        fi
ENDSSH
fi

echo ""
echo -e "${YELLOW}📤 Uploading files to instance using rsync...${NC}"

# Use rsync for efficient file transfer directly to server
rsync -avz --progress \
    --exclude='.git' \
    --exclude='.env' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.DS_Store' \
    --exclude='._*' \
    --exclude='venv' \
    --exclude='node_modules' \
    --exclude='media' \
    --exclude='staticfiles' \
    --exclude='db.sqlite3' \
    --exclude='*.log' \
    --exclude='terraform/.terraform' \
    --exclude='terraform/*.tfstate*' \
    -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
    "$PROJECT_DIR/" "ec2-user@$INSTANCE_IP:/home/ec2-user/twitter-bookmarks/" || {
    echo -e "${RED}❌ Error: Could not upload files${NC}"
    exit 1
}

echo ""
echo -e "${YELLOW}🔧 Setting up on instance...${NC}"

# SSH and fix permissions, then start
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ec2-user@$INSTANCE_IP << 'ENDSSH'
# Ensure directory exists and fix ownership
sudo mkdir -p /home/ec2-user/twitter-bookmarks
sudo chown -R ec2-user:ec2-user /home/ec2-user/twitter-bookmarks
sudo chmod 755 /home/ec2-user/twitter-bookmarks

# Clean up any macOS metadata files
find /home/ec2-user/twitter-bookmarks -name "._*" -type f -delete 2>/dev/null || true

# Ensure proper ownership and permissions
sudo chown -R ec2-user:ec2-user /home/ec2-user/twitter-bookmarks
chmod -R u+rw /home/ec2-user/twitter-bookmarks

cd /home/ec2-user/twitter-bookmarks

# Create .env file from template if it doesn't exist
if [ ! -f .env ]; then
    echo "⚠️  .env file not found. Creating from .env.example if available..."
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "✅ Created .env from .env.example"
        echo ""
        echo "⚠️  IMPORTANT: You must edit .env file with your actual values!"
        echo "   Required variables: SECRET_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, ENCRYPTION_KEY"
        echo ""
        echo "   To edit: ssh -i $SSH_KEY ec2-user@$INSTANCE_IP"
        echo "   Then: cd /home/ec2-user/twitter-bookmarks && nano .env"
        echo "   After editing, run: docker-compose -f docker-compose.prod.yml up -d --build"
        echo ""
        echo "   Or upload your .env file:"
        echo "   scp -i $SSH_KEY .env ec2-user@$INSTANCE_IP:/home/ec2-user/twitter-bookmarks/.env"
        echo ""
        exit 0
    else
        echo "❌ No .env.example found. You must create .env manually with required variables."
        echo "   See ENVIRONMENT_VARIABLES.md for required variables."
        echo ""
        echo "   To create: ssh -i $SSH_KEY ec2-user@$INSTANCE_IP"
        echo "   Then: cd /home/ec2-user/twitter-bookmarks && nano .env"
        echo ""
        exit 0
    fi
fi

# Start the application
echo "🚀 Starting application..."

# Use docker compose (v2) if available, fallback to docker-compose (v1)
if command -v docker &> /dev/null && docker compose version &> /dev/null; then
    echo "Using Docker Compose v2..."
    docker compose -f docker-compose.prod.yml down || true
    docker compose -f docker-compose.prod.yml up -d --build
elif command -v docker-compose &> /dev/null; then
    echo "Using Docker Compose v1..."
    docker-compose -f docker-compose.prod.yml down || true
    docker-compose -f docker-compose.prod.yml up -d --build
else
    echo "❌ Error: Docker Compose not found!"
    echo "Please install Docker Compose:"
    echo "  sudo curl -L \"https://github.com/docker/compose/releases/latest/download/docker-compose-\$(uname -s)-\$(uname -m)\" -o /usr/local/bin/docker-compose"
    echo "  sudo chmod +x /usr/local/bin/docker-compose"
    exit 1
fi
ENDSSH

echo ""
echo -e "${GREEN}✅ Application uploaded and started!${NC}"
echo ""
echo "Application URL: http://$INSTANCE_IP:8000"
echo ""
echo "To check logs:"
echo "  ssh -i $SSH_KEY ec2-user@$INSTANCE_IP"
echo "  cd /home/ec2-user/twitter-bookmarks"
echo "  ./logs.sh"
echo "  # or: docker-compose -f docker-compose.prod.yml logs -f"

