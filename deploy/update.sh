#!/bin/bash
# OpenEvent AI - Quick Update Script
# Run after pushing changes to git
# Usage: ssh your-vps "cd /var/www/openevent && ./deploy/update.sh"

set -e

cd /var/www/openevent

echo "Pulling latest changes..."
git pull origin main

echo "Installing any new dependencies..."
./venv/bin/pip install -r requirements-dev

echo "Restarting service..."
sudo systemctl restart openevent

echo "Done! Checking status..."
sudo systemctl status openevent --no-pager
