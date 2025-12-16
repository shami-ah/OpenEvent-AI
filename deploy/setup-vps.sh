#!/bin/bash
# OpenEvent AI - Hostinger VPS Setup Script
# Run this on your VPS: ./deploy/setup-vps.sh

set -e

echo "=== OpenEvent AI - Hostinger VPS Setup ==="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo ./deploy/setup-vps.sh"
    exit 1
fi

# Update system
echo "[1/6] Updating system packages..."
apt update && apt upgrade -y

# Install dependencies
echo "[2/6] Installing Python, nginx, and dependencies..."
apt install -y python3 python3-pip python3-venv nginx git curl

# Setup application directory
APP_DIR="/opt/openevent"
echo "[3/6] Setting up application in ${APP_DIR}..."

if [ -d "$APP_DIR" ] && [ -d "$APP_DIR/.git" ]; then
    echo "  Repository exists, pulling latest..."
    cd $APP_DIR
    git pull origin main
else
    echo "  Repository should already be cloned (you ran this script from it)"
    # If running from the cloned repo, just ensure we're in the right place
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    REPO_DIR="$(dirname "$SCRIPT_DIR")"

    if [ "$REPO_DIR" != "$APP_DIR" ]; then
        echo "  Moving/copying repository to ${APP_DIR}..."
        mkdir -p $APP_DIR
        cp -r "$REPO_DIR"/* $APP_DIR/
        cp -r "$REPO_DIR"/.* $APP_DIR/ 2>/dev/null || true
    fi
fi

cd $APP_DIR

# Create virtual environment
echo "[4/6] Setting up Python virtual environment..."
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

# Create .env file if not exists
echo "[5/6] Creating environment file..."
if [ ! -f ".env" ]; then
    cat > .env << 'EOF'
# OpenEvent AI Environment Configuration
# IMPORTANT: Add your actual OpenAI API key below!

OPENAI_API_KEY=sk-your-openai-api-key-here
AGENT_MODE=openai
OE_LLM_PROFILE=default
PYTHONDONTWRITEBYTECODE=1

# CORS - Allow Lovable frontend to connect
ALLOWED_ORIGINS=https://lovable.dev,https://*.lovable.app,http://localhost:3000
EOF
    echo ""
    echo "  *** IMPORTANT: Edit /opt/openevent/.env and add your OPENAI_API_KEY! ***"
    echo ""
fi

# Install and enable systemd service
echo "[6/6] Installing systemd service..."
cp deploy/openevent.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable openevent

# Open firewall port
if command -v ufw &> /dev/null; then
    ufw allow 8000/tcp
    ufw allow 80/tcp
    ufw allow 443/tcp
fi

# Setup nginx (optional - can use direct port 8000)
if [ -f "deploy/nginx-openevent.conf" ]; then
    cp deploy/nginx-openevent.conf /etc/nginx/sites-available/openevent
    ln -sf /etc/nginx/sites-available/openevent /etc/nginx/sites-enabled/
    rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
    nginx -t && systemctl reload nginx
fi

echo ""
echo "=========================================="
echo "  Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Add your OpenAI API key:"
echo "   nano /opt/openevent/.env"
echo ""
echo "2. Start the backend:"
echo "   systemctl start openevent"
echo ""
echo "3. Check it's running:"
echo "   systemctl status openevent"
echo "   curl http://localhost:8000/api/workflow/health"
echo ""
echo "4. Test from outside:"
echo "   curl http://72.60.135.183:8000/api/workflow/health"
echo ""
echo "5. Tell your Lovable colleague to set:"
echo "   VITE_BACKEND_BASE=http://72.60.135.183:8000"
echo ""
echo "Logs: journalctl -u openevent -f"
echo ""
