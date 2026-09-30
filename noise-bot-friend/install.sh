#!/usr/bin/env bash
set -e

echo "=========================================================="
echo "  🔊 Edmonton Traffic Noise Monitor — IoT Installer"
echo "  Target: Raspberry Pi (Debian/Raspbian)"
echo "=========================================================="

INSTALL_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

# 1. Ensure Wi-Fi radio is unblocked and Regulatory Domain is set
echo ">> Unblocking Wi-Fi radio and setting regulatory domain (CA)..."
sudo raspi-config nonint do_wifi_country CA || true
sudo nmcli radio wifi on || true

# 1a. Disable Wi-Fi Power Saving (Prevents packet drops, sleep latency, and false offline status)
echo ">> Disabling Wi-Fi power saving..."
sudo mkdir -p /etc/NetworkManager/conf.d
echo -e "[connection]\nwifi.powersave = 2" | sudo tee /etc/NetworkManager/conf.d/default-wifi-powersave-off.conf > /dev/null
sudo iw dev wlan0 set power_save off 2>/dev/null || true

# 1b. Check & Install Network Management dependencies for IoT Hotspot
echo ">> Checking NetworkManager and DNS dependencies for IoT Hotspot..."
if ! command -v nmcli &> /dev/null || ! dpkg -l | grep -q dnsmasq-base; then
    echo ">> Installing network-manager and dnsmasq-base for Captive Portal..."
    sudo apt-get update && sudo apt-get install -y network-manager dnsmasq-base
fi

# 2. Configure Captive Portal DNS Redirection (All DNS queries resolve to 192.168.4.1 in Hotspot mode)
sudo mkdir -p /etc/NetworkManager/dnsmasq-shared.d
echo "address=/#/192.168.4.1" | sudo tee /etc/NetworkManager/dnsmasq-shared.d/noise-bot-captive.conf > /dev/null

# 3. Install and Enable IoT Auto-Provisioner Systemd Service
echo ">> Installing IoT Wi-Fi Auto-Provisioner Service..."
sudo tee /etc/systemd/system/noise-bot-provisioner.service > /dev/null <<EOF
[Unit]
Description=Edmonton Noise Bot IoT Wi-Fi Hotspot Auto-Provisioner
After=NetworkManager.service
Wants=NetworkManager.service

[Service]
Type=oneshot
User=root
Environment=PYTHONUNBUFFERED=1
WorkingDirectory=${INSTALL_DIR}/provisioner
ExecStart=/usr/bin/python3 -u ${INSTALL_DIR}/provisioner/wifi_provisioner.py
RemainAfterExit=no

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable noise-bot-provisioner.service

# 3b. Install NetworkManager Dispatcher Script (Launches hotspot immediately if Ethernet is unplugged)
echo ">> Installing NetworkManager carrier-drop auto-trigger..."
sudo mkdir -p /etc/NetworkManager/dispatcher.d
sudo tee /etc/NetworkManager/dispatcher.d/99-noisebot-hotspot.sh > /dev/null << 'DISPATCH_EOF'
#!/usr/bin/env bash
IFACE="$1"
ACTION="$2"

if [ "$ACTION" = "down" ] || [ "$ACTION" = "connectivity-change" ]; then
    if ! ip route show default | grep -q default; then
        if ! systemctl is-active --quiet noise-bot-provisioner.service; then
            systemctl start noise-bot-provisioner.service
        fi
    fi
fi
DISPATCH_EOF
sudo chmod +x /etc/NetworkManager/dispatcher.d/99-noisebot-hotspot.sh

echo ">> IoT Auto-Provisioner & Carrier Watcher successfully armed!"

# 4. Check for Docker
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

# 5. Check for Docker Compose
if ! docker compose version &> /dev/null; then
    echo ">> Installing Docker Compose plugin..."
    sudo apt-get update && sudo apt-get install -y docker-compose-plugin
fi

# 6. Set up ALSA / Audio permissions
sudo usermod -aG audio "$USER" || true

# 7. Prepare directories and state files
cd "$INSTALL_DIR"
mkdir -p recordings
touch noise_bot.log

# Ensure live_audio_state.json is a valid JSON file
if [ -d "live_audio_state.json" ]; then
    rm -rf live_audio_state.json
fi
if [ ! -f "live_audio_state.json" ] || [ ! -s "live_audio_state.json" ]; then
    echo '{"current_dba": 0.0, "is_recording": false, "last_updated": 0}' > live_audio_state.json
fi

# Ensure fleet_database.json is a valid JSON file and not a directory from a failed bind mount
if [ -d "fleet_database.json" ]; then
    echo ">> Removing erroneously created fleet_database.json directory..."
    rm -rf fleet_database.json
fi
if [ ! -f "fleet_database.json" ] || [ ! -s "fleet_database.json" ]; then
    echo "{}" > fleet_database.json
fi

# Ensure scripts are executable
chmod +x provisioner/wifi_provisioner.py 2>/dev/null || true
if [ -f "factory_reset.sh" ]; then
    chmod +x factory_reset.sh
fi

# If config.json doesn't exist, create it from example template
if [ ! -f "config.json" ]; then
    echo ">> Creating config.json from template..."
    cp config.example.json config.json
fi

# 8. Start Noise Bot containers
echo ">> Pulling and starting Traffic Noise Monitor containers..."
docker compose pull || sudo docker compose pull || true
docker compose up -d || sudo docker compose up -d

IP_ADDR=$(hostname -I | awk '{print $1}')
MDNS_NAME=$(hostname)

echo ""
echo "=========================================================="
echo "  🎉 Installation Complete!"
echo "=========================================================="
echo "  📡 IoT Out-of-the-Box Mode: ACTIVE"
echo "  • If Wi-Fi is ever lost or unplugged, the Pi will"
echo "    automatically broadcast 'Edmonton-Noise-Bot-Setup'!"
echo ""
echo "  Open the dashboard right now at:"
if [ -n "$IP_ADDR" ]; then
    echo "  👉 http://${IP_ADDR}:5000"
fi
echo "  👉 http://${MDNS_NAME}.local:5000"
echo "  👉 http://noise-bot.local:5000"
echo ""
echo "  Admin Passcode: 1811 (or your custom passcode)"
echo "  Auto-Updates:   Watchtower active (every 5 mins)"
echo "=========================================================="
