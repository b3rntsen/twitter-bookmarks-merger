#!/bin/bash
# Script to upgrade EC2 instance from t3.micro to t3.small
# This script automates the upgrade process

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TERRAFORM_DIR="$PROJECT_DIR/terraform"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 EC2 Instance Upgrade Script${NC}"
echo "This will upgrade your instance from t3.micro to t3.small"
echo ""

# Check if we're in the right directory
if [ ! -d "$TERRAFORM_DIR" ]; then
    echo -e "${RED}Error: terraform directory not found${NC}"
    exit 1
fi

# Get current instance IP
echo -e "${YELLOW}Step 1: Getting current instance information...${NC}"
cd "$TERRAFORM_DIR"
CURRENT_IP=$(terraform output -raw public_ip 2>/dev/null || echo "")
if [ -z "$CURRENT_IP" ]; then
    echo -e "${RED}Error: Could not get current instance IP from Terraform${NC}"
    echo "Please run this from the terraform directory or check your Terraform state"
    exit 1
fi

echo "Current instance IP: $CURRENT_IP"

# Check SSH key
SSH_KEY="$HOME/.ssh/twitter-bookmarks-key.pem"
if [ ! -f "$SSH_KEY" ]; then
    echo -e "${RED}Error: SSH key not found at $SSH_KEY${NC}"
    exit 1
fi

# Backup confirmation
echo ""
echo -e "${YELLOW}Step 2: Creating backups...${NC}"
echo "Backing up .env file and database from current instance..."

ssh -i "$SSH_KEY" ec2-user@$CURRENT_IP << 'EOF'
cd /home/ec2-user/twitter-bookmarks
cp .env ~/.env.backup 2>/dev/null || echo "Warning: .env not found"
cp db.sqlite3 ~/db.sqlite3.backup 2>/dev/null || echo "No SQLite DB found"
echo "Backups created in home directory"
EOF

echo -e "${GREEN}✓ Backups created${NC}"

# Update Terraform
echo ""
echo -e "${YELLOW}Step 3: Updating Terraform configuration...${NC}"
echo "The default instance type is now t3.small"
echo "Reviewing Terraform plan..."

terraform plan -out=tfplan

echo ""
read -p "Do you want to proceed with creating the new instance? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 1
fi

# Apply Terraform
echo ""
echo -e "${YELLOW}Step 4: Creating new instance...${NC}"
terraform apply tfplan

# Get new instance IP
NEW_IP=$(terraform output -raw public_ip)
echo -e "${GREEN}✓ New instance created: $NEW_IP${NC}"

# Wait for instance to be ready
echo ""
echo -e "${YELLOW}Step 5: Waiting for new instance to be ready...${NC}"
sleep 30

# Test SSH connection
echo "Testing SSH connection..."
for i in {1..10}; do
    if ssh -i "$SSH_KEY" -o ConnectTimeout=5 -o StrictHostKeyChecking=no ec2-user@$NEW_IP "echo 'Connection successful'" 2>/dev/null; then
        echo -e "${GREEN}✓ Instance is ready${NC}"
        break
    fi
    if [ $i -eq 10 ]; then
        echo -e "${RED}Error: Could not connect to new instance${NC}"
        exit 1
    fi
    echo "Waiting... ($i/10)"
    sleep 10
done

# Copy files
echo ""
echo -e "${YELLOW}Step 6: Copying application files...${NC}"
echo "This may take a few minutes..."

rsync -avz -e "ssh -i $SSH_KEY" \
  --exclude='.git' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.DS_Store' \
  --exclude='*.log' \
  ec2-user@$CURRENT_IP:/home/ec2-user/twitter-bookmarks/ \
  ec2-user@$NEW_IP:/home/ec2-user/twitter-bookmarks/

echo -e "${GREEN}✓ Files copied${NC}"

# Set permissions and start application
echo ""
echo -e "${YELLOW}Step 7: Starting application on new instance...${NC}"

ssh -i "$SSH_KEY" ec2-user@$NEW_IP << 'EOF'
cd /home/ec2-user/twitter-bookmarks
sudo chown -R ec2-user:ec2-user /home/ec2-user/twitter-bookmarks
sudo chmod -R 755 /home/ec2-user/twitter-bookmarks
docker compose -f docker-compose.prod.yml up -d
echo "Application started"
EOF

echo -e "${GREEN}✓ Application started${NC}"

# Summary
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}Upgrade Complete!${NC}"
echo ""
echo "Old instance IP: $CURRENT_IP"
echo "New instance IP: $NEW_IP"
echo ""
echo "The Elastic IP has been automatically associated with the new instance."
echo "DNS should update automatically (Route 53)."
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Visit https://twitter.dethele.com to verify the application works"
echo "2. Test login and functionality"
echo "3. Once verified, you can terminate the old instance:"
echo "   aws ec2 terminate-instances --instance-ids <OLD_INSTANCE_ID>"
echo ""
echo -e "${YELLOW}To get the old instance ID:${NC}"
echo "   aws ec2 describe-instances --filters \"Name=ip-address,Values=$CURRENT_IP\" --query 'Reservations[0].Instances[0].InstanceId' --output text"
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"

