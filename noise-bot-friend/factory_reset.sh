#!/usr/bin/env bash
set -e

APP_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

echo "======================================================="
echo "   Edmonton Noise Bot — Factory Out-Of-The-Box Reset"
echo "======================================================="

# 1. Stop containers
echo ">> [1/6] Stopping Docker containers..."
docker stop noise-bot-app noise-bot-watchtower 2>/dev/null || true

# 2. Clear old recordings, logs, and live states
echo ">> [2/6] Cleaning recordings, logs, and live telemetry..."
mkdir -p "$APP_DIR/recordings"
rm -f "$APP_DIR/recordings"/*.wav
rm -f "$APP_DIR/recordings"/*.mp3
> "$APP_DIR/noise_bot.log"
echo '{"current_dba": 0.0, "is_recording": false, "last_updated": 0}' > "$APP_DIR/live_audio_state.json"

if [ -d "$APP_DIR/fleet_database.json" ]; then
    rm -rf "$APP_DIR/fleet_database.json"
fi
echo '{}' > "$APP_DIR/fleet_database.json"

# 3. Reset config.json to fresh out-of-the-box defaults
echo ">> [3/6] Resetting config.json to factory defaults..."
if [ -f "$APP_DIR/config.example.json" ]; then
    cp "$APP_DIR/config.example.json" "$APP_DIR/config.json"
else
    cat << 'EOF' > "$APP_DIR/config.json"
{
  "admin_passcode": "1811",
  "location_name": "Balcony Station",
  "street_name": "",
  "floor_number": 3,
  "horizontal_setback_meters": 5.0,
  "distance_to_road_meters": 7.8,
  "audio_device_index": null,
  "threshold_dba": 75.0,
  "calibration_offset": 50.0,
  "cooldown_period_minutes": 2,
  "record_event_seconds": 8,
  "save_audio_files": true,
  "output_directory": "./recordings",
  "bluesky": {
    "enabled": false,
    "handle": "",
    "app_password": "",
    "target_handles": []
  },
  "fleet_hub": {
    "enabled": true,
    "hub_url": "https://sethdear.ca/yegnoise",
    "station_id": "",
    "station_name": ""
  }
}
EOF
fi

# 4. Ensure provisioner service is enabled and Wi-Fi power saving is disabled
echo ">> [4/6] Ensuring IoT Wi-Fi auto-provisioner is enabled & Wi-Fi power saving disabled..."
systemctl enable noise-bot-provisioner.service 2>/dev/null || true
mkdir -p /etc/NetworkManager/conf.d
echo -e "[connection]\nwifi.powersave = 2" > /etc/NetworkManager/conf.d/default-wifi-powersave-off.conf
iw dev wlan0 set power_save off 2>/dev/null || true

# 5. Forget saved Wi-Fi connections
echo ">> [5/6] Forgetting saved Wi-Fi credentials (leaving Ethernet intact)..."
for uuid in $(nmcli -t -f UUID,TYPE connection show | grep -E ':(802-11-wireless|wifi)$' | cut -d: -f1); do
    echo "   Removing saved Wi-Fi connection UUID: $uuid"
    nmcli connection delete "$uuid" 2>/dev/null || true
done
nmcli connection delete NoiseBotSetup 2>/dev/null || true

# 6. Shut down cleanly
echo ">> [6/6] Shutting down system for unboxing..."
echo "======================================================="
echo "   Factory Reset Complete!"
echo "   Powering off system safely in 3 seconds..."
echo "   When booted without Wi-Fi, it will broadcast:"
echo "   'Edmonton-Noise-Bot-Setup' at http://192.168.4.1"
echo "======================================================="
sleep 3
poweroff
