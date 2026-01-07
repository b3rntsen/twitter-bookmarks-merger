#!/bin/bash
# Install Redis for local development
# Supports macOS (Homebrew) and Linux (apt/yum)

set -e

echo "Installing Redis for local development..."

# Detect OS
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    if command -v brew &> /dev/null; then
        echo "Detected macOS with Homebrew. Installing Redis..."
        brew install redis
        echo "Starting Redis service..."
        brew services start redis
        echo "✅ Redis installed and started via Homebrew"
        echo "To start Redis manually: brew services start redis"
        echo "To stop Redis: brew services stop redis"
    else
        echo "❌ Homebrew not found. Please install Homebrew first:"
        echo "   /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
        exit 1
    fi
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Linux
    if command -v apt-get &> /dev/null; then
        echo "Detected Debian/Ubuntu. Installing Redis..."
        sudo apt-get update
        sudo apt-get install -y redis-server
        echo "Starting Redis service..."
        sudo systemctl enable redis-server
        sudo systemctl start redis-server
        echo "✅ Redis installed and started"
    elif command -v yum &> /dev/null; then
        echo "Detected RHEL/CentOS. Installing Redis..."
        sudo yum install -y redis
        echo "Starting Redis service..."
        sudo systemctl enable redis
        sudo systemctl start redis
        echo "✅ Redis installed and started"
    else
        echo "❌ Unsupported Linux distribution. Please install Redis manually."
        exit 1
    fi
else
    echo "❌ Unsupported OS: $OSTYPE"
    echo "Please install Redis manually for your platform."
    exit 1
fi

# Test Redis connection
echo ""
echo "Testing Redis connection..."
if redis-cli ping > /dev/null 2>&1; then
    echo "✅ Redis is running and responding to commands"
    echo ""
    echo "Redis is ready to use with Django-Q!"
    echo "Configure in .env:"
    echo "  REDIS_HOST=localhost"
    echo "  REDIS_PORT=6379"
    echo "  REDIS_DB=0"
else
    echo "⚠️  Redis installation completed but connection test failed."
    echo "   Please check Redis is running: redis-cli ping"
fi

