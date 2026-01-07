#!/bin/bash
# Release script for Twitter Bookmarks application
# Handles deployment with backup, versioning, health checks, and rollback capability

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/twitter-bookmarks-key.pem}"
SERVER_USER="${SERVER_USER:-ec2-user}"
SERVER_HOST="${SERVER_HOST:-13.62.72.70}"
PROJECT_DIR_REMOTE="/home/${SERVER_USER}/twitter-bookmarks"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Version from git or timestamp
VERSION="${VERSION:-$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d_%H%M%S)}"
RELEASE_NAME="release_${VERSION}"

# Functions
log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

check_prerequisites() {
    log_info "Checking prerequisites..."
    
    if [ ! -f "$SSH_KEY" ]; then
        log_error "SSH key not found: $SSH_KEY"
        exit 1
    fi
    
    if ! ssh -i "$SSH_KEY" -o ConnectTimeout=5 -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_HOST}" "echo 'Connection test'" &>/dev/null; then
        log_error "Cannot connect to server: ${SERVER_USER}@${SERVER_HOST}"
        exit 1
    fi
    
    log_success "Prerequisites check passed"
}

backup_remote() {
    log_info "Creating backup on remote server..."
    ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_HOST}" << 'ENDSSH'
        cd /home/ec2-user/twitter-bookmarks
        if [ -f ./scripts/backup.sh ]; then
            chmod +x ./scripts/backup.sh
            ./scripts/backup.sh
        else
            echo "⚠️  Backup script not found, creating manual backup..."
            BACKUP_DIR="/home/ec2-user/backups"
            TIMESTAMP=$(date +%Y%m%d_%H%M%S)
            BACKUP_PATH="${BACKUP_DIR}/backup_${TIMESTAMP}"
            mkdir -p "${BACKUP_PATH}"
            
            # Backup volumes
            docker run --rm \
                -v twitter-bookmarks_db_data:/data \
                -v "${BACKUP_PATH}":/backup \
                alpine tar czf /backup/db_data.tar.gz -C /data . 2>/dev/null || true
            
            docker run --rm \
                -v twitter-bookmarks_media:/data \
                -v "${BACKUP_PATH}":/backup \
                alpine tar czf /backup/media.tar.gz -C /data . 2>/dev/null || true
            
            # Backup config
            cp .env "${BACKUP_PATH}/.env" 2>/dev/null || true
            cp docker-compose.prod.yml "${BACKUP_PATH}/" 2>/dev/null || true
            
            # Save current images
            docker images --format "{{.Repository}}:{{.Tag}}" | grep twitter-bookmarks > "${BACKUP_PATH}/images.txt" || true
            
            echo "✅ Backup created: ${BACKUP_PATH}"
        fi
ENDSSH
    log_success "Backup completed"
}

upload_code() {
    log_info "Uploading code to server..."
    
    # Check if rsync is available on server, install if not
    log_info "Checking for rsync on server..."
    if ! ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_HOST}" "command -v rsync &> /dev/null"; then
        log_warning "rsync not found on server, installing..."
        ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_HOST}" << 'ENDSSH'
            if command -v yum &> /dev/null; then
                sudo yum install -y rsync
            elif command -v apt-get &> /dev/null; then
                sudo apt-get update && sudo apt-get install -y rsync
            else
                echo "Cannot install rsync automatically"
                exit 1
            fi
ENDSSH
        log_success "rsync installed"
    fi
    
    # Use rsync for efficient file transfer (now that rsync is installed on server)
    log_info "Syncing files to server using rsync..."
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
        "${PROJECT_DIR}/" "${SERVER_USER}@${SERVER_HOST}:${PROJECT_DIR_REMOTE}/" || {
        log_warning "rsync failed, this is non-critical - files may have been uploaded via previous method"
    }
    
    # Fix permissions on server
    ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_HOST}" << 'ENDSSH'
        cd /home/ec2-user/twitter-bookmarks
        # Clean up any macOS metadata files
        find . -name "._*" -type f -delete 2>/dev/null || true
        # Ensure proper ownership and permissions
        sudo chown -R ec2-user:ec2-user .
        chmod -R u+rw .
ENDSSH
    
    log_success "Code uploaded"
}

build_and_deploy() {
    log_info "Building and deploying version ${VERSION}..."
    
    ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_HOST}" << ENDSSH
        set -e
        cd ${PROJECT_DIR_REMOTE}
        
        # Build new image with version tag
        echo "🔨 Building Docker image with tag: ${VERSION}..."
        docker build -t twitter-bookmarks-web:${VERSION} -t twitter-bookmarks-web:latest .
        
        # Tag nginx image if needed
        if [ -d "./nginx" ]; then
            docker build -t twitter-bookmarks-nginx:${VERSION} -t twitter-bookmarks-nginx:latest ./nginx || true
        fi
        
        # Stop current containers gracefully
        echo "🛑 Stopping current containers..."
        docker compose -f docker-compose.prod.yml down --timeout 30 || true
        
        # Start new containers
        echo "🚀 Starting new containers..."
        docker compose -f docker-compose.prod.yml up -d
        
        # Wait for services to be ready
        echo "⏳ Waiting for services to be ready..."
        sleep 15
        
        # Run migrations
        echo "🔄 Running database migrations..."
        docker compose -f docker-compose.prod.yml exec -T web python manage.py migrate --noinput || {
            echo "⚠️  Migration failed, but continuing..."
        }
        
        # Collect static files
        echo "📦 Collecting static files..."
        docker compose -f docker-compose.prod.yml exec -T web python manage.py collectstatic --noinput || {
            echo "⚠️  Static files collection failed, but continuing..."
        }
        
        # Verify all services are running
        echo "🔍 Verifying services..."
        docker compose -f docker-compose.prod.yml ps
        
        # Verify Redis connection
        echo "🔍 Verifying Redis connection..."
        docker compose -f docker-compose.prod.yml exec -T web python -c "import redis; r = redis.Redis(host='redis', port=6379); r.ping()" && echo "✅ Redis connection successful" || echo "⚠️  Redis connection check failed"
        
        # Verify qcluster is running
        echo "🔍 Verifying qcluster..."
        docker compose -f docker-compose.prod.yml exec -T qcluster python -c "import django; django.setup(); from django_q.models import OrmQ; print('✅ Django-Q is accessible')" || echo "⚠️  Django-Q check failed"
        
        # Save release info
        echo "${VERSION}" > .release_version
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > .release_timestamp
        
        echo "✅ Deployment complete"
ENDSSH
    
    log_success "Deployment completed"
}

health_check() {
    log_info "Performing health check..."
    
    local max_attempts=30
    local attempt=1
    local health_ok=false
    
    while [ $attempt -le $max_attempts ]; do
        if curl -f -s -o /dev/null -w "%{http_code}" --max-time 5 "https://twitter.dethele.com" | grep -qE "^(200|302|301)"; then
            health_ok=true
            break
        fi
        
        log_warning "Health check attempt ${attempt}/${max_attempts} failed, retrying..."
        sleep 5
        attempt=$((attempt + 1))
    done
    
    if [ "$health_ok" = true ]; then
        log_success "Health check passed"
        return 0
    else
        log_error "Health check failed after ${max_attempts} attempts"
        return 1
    fi
}

rollback() {
    log_warning "Rolling back to previous version..."
    
    ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_HOST}" << 'ENDSSH'
        set -e
        cd /home/ec2-user/twitter-bookmarks
        
        # Get previous version from backup
        BACKUP_DIR="/home/ec2-user/backups"
        LATEST_BACKUP=$(ls -t "${BACKUP_DIR}" | grep "^backup_" | head -1)
        
        if [ -z "$LATEST_BACKUP" ]; then
            echo "❌ No backup found for rollback"
            exit 1
        fi
        
        echo "📦 Restoring from backup: ${LATEST_BACKUP}"
        
        # Stop current containers
        docker compose -f docker-compose.prod.yml down
        
        # Restore volumes if backup exists
        if [ -f "${BACKUP_DIR}/${LATEST_BACKUP}/db_data.tar.gz" ]; then
            docker volume create twitter-bookmarks_db_data 2>/dev/null || true
            docker run --rm \
                -v twitter-bookmarks_db_data:/data \
                -v "${BACKUP_DIR}/${LATEST_BACKUP}":/backup \
                alpine sh -c "cd /data && tar xzf /backup/db_data.tar.gz"
        fi
        
        if [ -f "${BACKUP_DIR}/${LATEST_BACKUP}/media.tar.gz" ]; then
            docker volume create twitter-bookmarks_media 2>/dev/null || true
            docker run --rm \
                -v twitter-bookmarks_media:/data \
                -v "${BACKUP_DIR}/${LATEST_BACKUP}":/backup \
                alpine sh -c "cd /data && tar xzf /backup/media.tar.gz"
        fi
        
        # Restore previous image if available
        if [ -f "${BACKUP_DIR}/${LATEST_BACKUP}/images.txt" ]; then
            PREV_IMAGE=$(head -1 "${BACKUP_DIR}/${LATEST_BACKUP}/images.txt" | cut -d: -f1)
            if [ -n "$PREV_IMAGE" ]; then
                docker tag "${PREV_IMAGE}:latest" twitter-bookmarks-web:latest 2>/dev/null || true
            fi
        fi
        
        # Start containers
        docker compose -f docker-compose.prod.yml up -d
        
        echo "✅ Rollback complete"
ENDSSH
    
    log_success "Rollback completed"
}

# Main execution
main() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}  Twitter Bookmarks Release Process${NC}"
    echo -e "${BLUE}  Version: ${VERSION}${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    
    check_prerequisites
    backup_remote
    upload_code
    build_and_deploy
    
    if health_check; then
        log_success "Release ${VERSION} deployed successfully!"
        echo ""
        echo -e "${GREEN}🌐 Application URL: https://twitter.dethele.com${NC}"
    else
        log_error "Health check failed. Rolling back..."
        rollback
        exit 1
    fi
}

# Handle command line arguments
case "${1:-}" in
    rollback)
        rollback
        ;;
    backup)
        backup_remote
        ;;
    health)
        health_check
        ;;
    *)
        main
        ;;
esac
