#!/bin/bash
set -e

echo "=== TikTok Auto Commenter Deployment ==="

# Pull latest code
echo "[1/7] Pulling latest code from git..."
cd /home/aichaguimaoune/TikTok-Auto-Commenter
git pull

# Install Python dependencies
echo "[2/7] Installing Python dependencies..."
pip install -r requirements.txt

# Install gunicorn
echo "[3/7] Installing gunicorn..."
pip install gunicorn

# Copy nginx config
echo "[4/7] Configuring nginx..."
sudo cp deploy/nginx.conf /etc/nginx/sites-available/tiktok-commenter
sudo ln -sf /etc/nginx/sites-available/tiktok-commenter /etc/nginx/sites-enabled/tiktok-commenter

# Copy systemd service
echo "[5/7] Configuring systemd service..."
sudo cp deploy/tiktok-commenter.service /etc/systemd/system/tiktok-commenter.service

# Reload systemd daemon
echo "[6/7] Reloading systemd daemon..."
sudo systemctl daemon-reload

# Restart services
echo "[7/7] Restarting services..."
sudo systemctl restart tiktok-commenter
sudo systemctl enable tiktok-commenter
sudo systemctl restart nginx

echo "=== Deployment complete! ==="
echo "App should be accessible at http://tiktok.shopinzo.bond"
