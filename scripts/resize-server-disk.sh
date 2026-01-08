#!/bin/bash
# Resize the EC2 root volume without replacing the instance
set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Configuration
SSH_KEY="${SSH_KEY:-~/.ssh/twitter-bookmarks-key.pem}"
SERVER_USER="${SERVER_USER:-ec2-user}"
SERVER_HOST="${SERVER_HOST:-13.62.72.70}"
AWS_REGION="${AWS_REGION:-eu-north-1}"
NEW_SIZE="${1:-60}"  # Default to 60GB, or pass as argument

echo -e "${GREEN}=== EC2 Volume Resize Script ===${NC}"
echo ""

# Check AWS CLI is installed
if ! command -v aws &> /dev/null; then
    echo -e "${RED}Error: AWS CLI not installed${NC}"
    echo "Install with: brew install awscli"
    exit 1
fi

# Check AWS credentials
if ! aws sts get-caller-identity &> /dev/null; then
    echo -e "${RED}Error: AWS credentials not configured${NC}"
    echo "Run: aws configure"
    exit 1
fi

# Get instance ID from the server's IP
echo -e "${YELLOW}Finding instance by IP ${SERVER_HOST}...${NC}"
INSTANCE_ID=$(aws ec2 describe-instances \
    --filters "Name=ip-address,Values=${SERVER_HOST}" \
    --query 'Reservations[0].Instances[0].InstanceId' \
    --output text \
    --region "$AWS_REGION" 2>/dev/null)

# If not found by public IP, try private IP or Elastic IP
if [ -z "$INSTANCE_ID" ] || [ "$INSTANCE_ID" = "None" ]; then
    echo "Trying Elastic IP association..."
    INSTANCE_ID=$(aws ec2 describe-addresses \
        --filters "Name=public-ip,Values=${SERVER_HOST}" \
        --query 'Addresses[0].InstanceId' \
        --output text \
        --region "$AWS_REGION" 2>/dev/null)
fi

if [ -z "$INSTANCE_ID" ] || [ "$INSTANCE_ID" = "None" ]; then
    echo -e "${RED}Error: Could not find instance for IP ${SERVER_HOST}${NC}"
    echo ""
    echo "You can specify the instance ID manually:"
    echo "  INSTANCE_ID=i-xxxxx $0 $NEW_SIZE"
    exit 1
fi

echo -e "Instance ID: ${GREEN}${INSTANCE_ID}${NC}"

# Get volume ID
echo -e "${YELLOW}Getting volume ID...${NC}"
VOLUME_ID=$(aws ec2 describe-instances \
    --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].BlockDeviceMappings[0].Ebs.VolumeId' \
    --output text \
    --region "$AWS_REGION")

if [ -z "$VOLUME_ID" ] || [ "$VOLUME_ID" = "None" ]; then
    echo -e "${RED}Error: Could not find volume for instance${NC}"
    exit 1
fi

echo -e "Volume ID: ${GREEN}${VOLUME_ID}${NC}"

# Get current volume size
CURRENT_SIZE=$(aws ec2 describe-volumes \
    --volume-ids "$VOLUME_ID" \
    --query 'Volumes[0].Size' \
    --output text \
    --region "$AWS_REGION")

echo -e "Current size: ${YELLOW}${CURRENT_SIZE}GB${NC}"
echo -e "New size: ${GREEN}${NEW_SIZE}GB${NC}"
echo ""

if [ "$CURRENT_SIZE" -ge "$NEW_SIZE" ]; then
    echo -e "${YELLOW}Volume is already ${CURRENT_SIZE}GB (>= ${NEW_SIZE}GB)${NC}"
    echo "To shrink a volume, you must create a new smaller volume and migrate data."
    exit 0
fi

# Calculate cost difference
COST_DIFF=$(echo "scale=2; ($NEW_SIZE - $CURRENT_SIZE) * 0.092" | bc)
echo -e "Estimated additional cost: ${YELLOW}\$${COST_DIFF}/month${NC}"
echo ""

# Confirm
read -p "Proceed with resize? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

# Resize the volume
echo ""
echo -e "${YELLOW}Resizing volume to ${NEW_SIZE}GB...${NC}"
aws ec2 modify-volume \
    --volume-id "$VOLUME_ID" \
    --size "$NEW_SIZE" \
    --region "$AWS_REGION"

# Wait for modification to complete
echo -e "${YELLOW}Waiting for volume modification to complete...${NC}"
while true; do
    STATE=$(aws ec2 describe-volumes-modifications \
        --volume-id "$VOLUME_ID" \
        --query 'VolumesModifications[0].ModificationState' \
        --output text \
        --region "$AWS_REGION" 2>/dev/null)

    if [ "$STATE" = "completed" ] || [ "$STATE" = "optimizing" ]; then
        echo -e "Volume modification: ${GREEN}${STATE}${NC}"
        break
    elif [ "$STATE" = "failed" ]; then
        echo -e "${RED}Volume modification failed!${NC}"
        exit 1
    else
        echo "  Status: $STATE (waiting...)"
        sleep 5
    fi
done

# Extend filesystem on the server
echo ""
echo -e "${YELLOW}Extending filesystem on server...${NC}"
ssh -i "$SSH_KEY" "${SERVER_USER}@${SERVER_HOST}" << 'ENDSSH'
echo "Current disk usage:"
df -h /

echo ""
echo "Extending partition..."
sudo growpart /dev/nvme0n1 1 2>/dev/null || echo "Partition already at max size"

echo "Extending filesystem..."
sudo xfs_growfs / 2>/dev/null || sudo resize2fs /dev/nvme0n1p1 2>/dev/null

echo ""
echo "New disk usage:"
df -h /
ENDSSH

echo ""
echo -e "${GREEN}Volume resize complete!${NC}"
echo ""
echo "Summary:"
echo "  Instance: $INSTANCE_ID"
echo "  Volume: $VOLUME_ID"
echo "  Old size: ${CURRENT_SIZE}GB"
echo "  New size: ${NEW_SIZE}GB"
