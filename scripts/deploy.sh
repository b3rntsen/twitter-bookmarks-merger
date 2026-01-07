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

echo -e "${GREEN}🚀 Deploying Twitter Bookmarks to AWS${NC}"
echo ""

# Check if AWS credentials are set
if [ -z "$AWS_ACCESS_KEY_ID" ] || [ -z "$AWS_SECRET_ACCESS_KEY" ]; then
    echo -e "${RED}❌ Error: AWS credentials not found in environment${NC}"
    echo ""
    echo "Please set the following environment variables:"
    echo "  export AWS_ACCESS_KEY_ID=your-access-key"
    echo "  export AWS_SECRET_ACCESS_KEY=your-secret-key"
    echo "  export AWS_DEFAULT_REGION=us-east-1  # optional, defaults to us-east-1"
    echo ""
    exit 1
fi

# Check if Terraform is installed
if ! command -v terraform &> /dev/null; then
    echo -e "${RED}❌ Error: Terraform is not installed${NC}"
    echo ""
    echo "Install Terraform:"
    echo "  macOS: brew install terraform"
    echo "  Linux: https://developer.hashicorp.com/terraform/downloads"
    echo ""
    exit 1
fi

# Check if jq is installed (for pretty output)
if ! command -v jq &> /dev/null; then
    echo -e "${YELLOW}⚠️  Warning: jq not installed. Install for better output formatting${NC}"
    echo "  macOS: brew install jq"
    echo "  Linux: sudo apt-get install jq"
    echo ""
fi

# Navigate to terraform directory
cd "$TERRAFORM_DIR"

# Initialize Terraform (if needed)
if [ ! -d ".terraform" ]; then
    echo -e "${YELLOW}📦 Initializing Terraform...${NC}"
    terraform init
fi

# Plan deployment
echo -e "${YELLOW}📋 Planning deployment...${NC}"
terraform plan -out=tfplan

# Ask for confirmation
read -p "Do you want to apply these changes? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Cancelled.${NC}"
    exit 0
fi

# Apply Terraform
echo -e "${YELLOW}🔨 Applying Terraform configuration...${NC}"
terraform apply tfplan
rm -f tfplan

# Get outputs
echo ""
echo -e "${GREEN}✅ Deployment complete!${NC}"
echo ""
echo "Instance details:"
if command -v jq &> /dev/null; then
    terraform output -json | jq -r '
      "Instance ID: " + .instance_id.value,
      "Public IP: " + .instance_public_ip.value,
      "Application URL: " + .application_url.value,
      "",
      "SSH Command:",
      .ssh_command.value
    '
else
    terraform output
fi

echo ""
echo -e "${YELLOW}📝 Next steps:${NC}"
echo "1. Upload your application code to the instance"
echo "2. Upload your .env file"
echo "3. SSH into the instance and run: cd /home/ec2-user/twitter-bookmarks && docker-compose up -d --build"
echo ""
echo "Or use the upload script: ./scripts/upload-to-aws.sh"

