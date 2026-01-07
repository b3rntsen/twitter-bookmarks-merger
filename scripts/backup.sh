#!/bin/bash
# Backup script for Twitter Bookmarks application
# Backs up database, volumes, and configuration

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-/home/ec2-user/backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="backup_${TIMESTAMP}"
BACKUP_PATH="${BACKUP_DIR}/${BACKUP_NAME}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}📦 Creating backup: ${BACKUP_NAME}${NC}"

# Create backup directory
mkdir -p "${BACKUP_PATH}"

# Backup database (if using SQLite)
if [ -f "${PROJECT_DIR}/db.sqlite3" ]; then
    echo -e "${YELLOW}  Backing up SQLite database...${NC}"
    cp "${PROJECT_DIR}/db.sqlite3" "${BACKUP_PATH}/db.sqlite3"
fi

# Backup Docker volumes
echo -e "${YELLOW}  Backing up Docker volumes...${NC}"
cd "${PROJECT_DIR}"

# Backup db_data volume
if docker volume inspect twitter-bookmarks_db_data &>/dev/null; then
    docker run --rm \
        -v twitter-bookmarks_db_data:/data \
        -v "${BACKUP_PATH}":/backup \
        alpine tar czf /backup/db_data.tar.gz -C /data .
    echo -e "${GREEN}  ✓ Database volume backed up${NC}"
fi

# Backup media volume
if docker volume inspect twitter-bookmarks_media &>/dev/null; then
    docker run --rm \
        -v twitter-bookmarks_media:/data \
        -v "${BACKUP_PATH}":/backup \
        alpine tar czf /backup/media.tar.gz -C /data .
    echo -e "${GREEN}  ✓ Media volume backed up${NC}"
fi

# Backup staticfiles volume
if docker volume inspect twitter-bookmarks_staticfiles &>/dev/null; then
    docker run --rm \
        -v twitter-bookmarks_staticfiles:/data \
        -v "${BACKUP_PATH}":/backup \
        alpine tar czf /backup/staticfiles.tar.gz -C /data .
    echo -e "${GREEN}  ✓ Static files volume backed up${NC}"
fi

# Backup configuration files
echo -e "${YELLOW}  Backing up configuration...${NC}"
mkdir -p "${BACKUP_PATH}/config"
cp "${PROJECT_DIR}/.env" "${BACKUP_PATH}/config/.env" 2>/dev/null || echo "  ⚠️  .env not found"
cp "${PROJECT_DIR}/docker-compose.prod.yml" "${BACKUP_PATH}/config/" 2>/dev/null || true

# Backup current image tags
echo -e "${YELLOW}  Saving current image information...${NC}"
docker images --format "{{.Repository}}:{{.Tag}}" | grep twitter-bookmarks > "${BACKUP_PATH}/images.txt" || true

# Create metadata file
cat > "${BACKUP_PATH}/backup_metadata.json" <<EOF
{
  "timestamp": "${TIMESTAMP}",
  "backup_name": "${BACKUP_NAME}",
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "project_dir": "${PROJECT_DIR}",
  "volumes": [
    "twitter-bookmarks_db_data",
    "twitter-bookmarks_media",
    "twitter-bookmarks_staticfiles"
  ]
}
EOF

# Create a symlink to latest backup
rm -f "${BACKUP_DIR}/latest"
ln -s "${BACKUP_NAME}" "${BACKUP_DIR}/latest"

echo -e "${GREEN}✅ Backup completed: ${BACKUP_PATH}${NC}"
echo -e "${YELLOW}  Backup size: $(du -sh "${BACKUP_PATH}" | cut -f1)${NC}"

# Cleanup old backups (keep last 10)
echo -e "${YELLOW}  Cleaning up old backups (keeping last 10)...${NC}"
cd "${BACKUP_DIR}"
ls -t | grep "^backup_" | tail -n +11 | xargs -r rm -rf

echo -e "${GREEN}✅ Backup process complete${NC}"
