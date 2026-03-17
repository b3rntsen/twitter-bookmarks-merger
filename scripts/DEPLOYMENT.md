# Deployment Scripts Guide

This document explains when to use each deployment script.

## Scripts Overview

### 🚀 Full Deployment (Infrastructure + Code)

**`./scripts/deploy.sh`**
- **Purpose**: Create/update AWS infrastructure with Terraform
- **Use when**: First-time setup or infrastructure changes (security groups, instance types, etc.)
- **What it does**:
  - Creates EC2 instance, security groups, elastic IP
  - Requires AWS credentials
  - Run once or when infrastructure changes needed

**`./scripts/upload-to-aws.sh`**
- **Purpose**: Complete code deployment with Docker rebuild
- **Use when**:
  - After infrastructure is created
  - Major changes (dependencies, Dockerfile, docker-compose changes)
  - First deployment to a new server
- **What it does**:
  - Syncs all code via rsync
  - Rebuilds Docker images from scratch
  - Starts all containers
- **Time**: ~5-10 minutes (full rebuild)

### ⚡ Quick Deployment (Code Only)

**`./scripts/quick-deploy.sh`** ⭐ **NEW**
- **Purpose**: Fast Python code updates without Docker rebuild
- **Use when**:
  - Django code changes (views, models, tasks, etc.)
  - Python scripts updates (tools/, birdmarks_bridge.py)
  - No changes to requirements.txt or Dockerfile
- **What it does**:
  - Syncs only Python code (web/, tools/, birdmarks/)
  - Copies to running containers
  - Clears Python cache
  - Restarts containers (no rebuild)
- **Time**: ~30 seconds

**`./scripts/deploy-to-production.sh`**
- **Purpose**: Code deployment with rebuild (slower than quick-deploy, faster than full)
- **Use when**:
  - Dependency changes (requirements.txt)
  - Significant code changes
  - Want to ensure clean build
- **What it does**:
  - Syncs code via rsync
  - Rebuilds Docker images
  - Restarts containers
- **Time**: ~2-3 minutes

### 📚 Static Files Only

**`./scripts/deploy-bookmarks.sh`**
- **Purpose**: Deploy static HTML bookmarks only
- **Use when**: Updating the static bookmark browser (from tools/bookmark_merger.py)
- **What it does**:
  - Syncs master/html/ and master/media/ to server
  - Does NOT touch Django app
- **Time**: Varies by media size (can be slow for 12GB media)

## Usage Examples

### Typical Development Workflow

```bash
# 1. Make changes to Django code (e.g., web/twitter/tasks.py)
vim web/twitter/tasks.py

# 2. Test locally
python manage.py test

# 3. Quick deploy (30 seconds)
./scripts/quick-deploy.sh

# 4. Check logs
ssh -i ~/.ssh/twitter-bookmarks-key.pem ec2-user@13.62.72.70 \
  'cd twitter-bookmarks && docker compose -f docker-compose.prod.yml logs -f qcluster'
```

### When You Add a New Dependency

```bash
# 1. Add to requirements.txt
echo "new-package==1.0.0" >> requirements.txt

# 2. Full deployment with rebuild (2-3 minutes)
./scripts/deploy-to-production.sh
```

### When You Change Dockerfile or docker-compose

```bash
# Use full upload + rebuild
./scripts/upload-to-aws.sh
```

## Decision Tree

```
Do you need to change infrastructure (EC2, security groups)?
├─ YES → ./scripts/deploy.sh (Terraform)
└─ NO → Continue...

Did you change requirements.txt, Dockerfile, or docker-compose.yml?
├─ YES → ./scripts/upload-to-aws.sh OR ./scripts/deploy-to-production.sh
└─ NO → Continue...

Did you only change Python code (*.py files)?
├─ YES → ./scripts/quick-deploy.sh ⚡ (FASTEST)
└─ NO → Continue...

Did you only change static bookmarks HTML?
├─ YES → ./scripts/deploy-bookmarks.sh
└─ NO → Use full deployment
```

## Troubleshooting

### Quick deploy doesn't seem to work
- Ensure Docker containers are running: `docker compose ps`
- Try full deployment: `./scripts/deploy-to-production.sh`
- Check if Python cache needs manual clearing

### Deployment hangs
- Check SSH key permissions: `chmod 400 ~/.ssh/twitter-bookmarks-key.pem`
- Verify server is accessible: `ssh -i ~/.ssh/twitter-bookmarks-key.pem ec2-user@13.62.72.70`

### Code changes not taking effect
- Clear Python cache: `find . -name "*.pyc" -delete && find . -name __pycache__ -delete`
- Restart containers: `docker compose -f docker-compose.prod.yml restart`
- If still not working, full rebuild: `./scripts/deploy-to-production.sh`

## Environment Variables

All scripts use these defaults (can be overridden):

```bash
export SSH_KEY="~/.ssh/twitter-bookmarks-key.pem"
export SERVER_USER="ec2-user"
export SERVER_HOST="13.62.72.70"
```

## Best Practices

1. **Always test locally first** before deploying
2. **Use quick-deploy for iterations** during development
3. **Use full deployment** for releases or after long periods
4. **Check logs** after deployment to verify success
5. **Keep backups** of .env and database before major changes
