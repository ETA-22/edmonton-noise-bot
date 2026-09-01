#!/usr/bin/env bash
set -e

echo "=========================================================="
echo "  🔊 Edmonton Traffic Noise Monitor — Installer"
echo "  Target: Raspberry Pi (Debian/Raspbian)"
echo "=========================================================="

# Check for Docker
if ! command -v docker &> /dev/null; then
    echo ">> Docker not found. Installing Docker CE automatically..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker "$USER"
    rm get-docker.sh
    echo ">> Docker installed successfully!"
else
    echo ">> Docker is already installed."
fi

# Check for Docker Compose
if ! docker compose version &> /dev/null; then
    echo ">> Installing Docker Compose plugin..."
    sudo apt-get update && sudo apt-get install -y docker-compose-plugin
fi

# Set up ALSA / Audio permissions
sudo usermod -aG audio "$USER" || true

# Prepare files and directories
mkdir -p recordings
touch live_audio_state.json
touch noise_bot.log
touch fleet_database.json

# If config.json doesn't exist, create it from example template
if [ ! -f "config.json" ]; then
    echo ">> Creating config.json from template..."
    cp config.example.json config.json
fi

echo ">> Pulling and starting Traffic Noise Monitor containers..."
docker compose pull || true
docker compose up -d

IP_ADDR=$(hostname -I | awk '{print $1}')

echo ""
echo "=========================================================="
echo "  🎉 Installation Complete!"
echo "=========================================================="
echo "  Open the dashboard on your phone/browser at:"
echo "  👉 http://${IP_ADDR}:5000"
echo "  👉 http://noise-bot.local:5000"
echo ""
echo "  Admin Passcode: admin123"
echo "  Auto-Updates:   Watchtower active (every 5 mins)"
echo "=========================================================="
