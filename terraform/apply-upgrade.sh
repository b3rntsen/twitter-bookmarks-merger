#!/bin/bash
# Quick script to apply the t3.small upgrade
set -e

cd "$(dirname "$0")"

echo "🚀 Upgrading instance to t3.small..."
echo ""
echo "This will:"
echo "  - Create a new t3.small instance"
echo "  - Reassociate the Elastic IP"
echo "  - Destroy the old t3.micro instance"
echo ""
echo "⚠️  Note: Application data on the old instance will be lost if not backed up."
echo "   Make sure you have your .env file and database backed up!"
echo ""
read -p "Continue? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Cancelled."
    exit 0
fi

# Apply the upgrade
terraform apply -var="instance_type=t3.small" -auto-approve

echo ""
echo "✅ Upgrade complete!"
echo ""
echo "New instance details:"
terraform output instance_public_ip
echo ""
echo "Next steps:"
echo "1. Upload application files: ./scripts/upload-to-aws.sh"
echo "2. SSH and start the app: ssh -i ~/.ssh/twitter-bookmarks-key.pem ec2-user@\$(terraform output -raw instance_public_ip)"
echo "3. Copy your .env file to the new instance"

