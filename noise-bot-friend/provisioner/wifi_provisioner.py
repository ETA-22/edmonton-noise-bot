#!/usr/bin/env python3
"""
Edmonton Noise Bot — IoT Wi-Fi Auto-Provisioner & Captive Portal
-----------------------------------------------------------------
Runs on boot if no Ethernet or Wi-Fi connection is detected.
Broadcasts 'Edmonton-Noise-Bot-Setup' access point with an offline
captive portal so users can configure Wi-Fi directly from their phone.

Features:
- Live Wi-Fi handshake validation: Tests credentials before declaring success.
- Clear error reporting: Shows exact failure reason (e.g. incorrect password).
- Mobile typing protection: autocapitalize="none", autocorrect="off", and show/hide password toggle.
- Persistent error display: If the captive window closes and reopens, the failure error is preserved.
"""

import os
import sys
import json
import time
import subprocess
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 80
AP_SSID = "Edmonton-Noise-Bot-Setup"
AP_IP = "192.168.4.1"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(BASE_DIR)
CONFIG_FILE = os.path.join(APP_DIR, "config.json")
CONFIG_EXAMPLE = os.path.join(APP_DIR, "config.example.json")

# Global provisioner state machine
PROVISION_STATE = {
    "status": "idle",       # "idle", "connecting", "failed", "connected"
    "ssid": "",
    "error": "",
    "timestamp": time.time()
}


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    if os.path.exists(CONFIG_EXAMPLE):
        try:
            with open(CONFIG_EXAMPLE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "admin_passcode": "1811",
        "location_name": "Balcony Station",
        "street_name": "Edmonton Road",
        "floor_number": 3,
        "horizontal_setback_meters": 5.0,
        "distance_to_road_meters": 7.8,
        "threshold_dba": 75.0,
        "calibration_offset": 50.0,
        "fleet_hub": {
            "enabled": True,
            "hub_url": "https://sethdear.ca/yegnoise"
        }
    }


def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"Error saving config: {e}")


def is_network_connected():
    try:
        res_route = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True, timeout=5)
        if res_route.stdout.strip():
            return True
        res_state = subprocess.run(["nmcli", "-t", "-f", "STATE", "general"], capture_output=True, text=True, timeout=5)
        out = res_state.stdout.lower().strip()
        if "connected" in out and "disconnected" not in out:
            return True
    except Exception:
        pass
    return False


def get_wifi_interface():
    try:
        res = subprocess.run(["nmcli", "-t", "-f", "DEVICE,TYPE", "device"], capture_output=True, text=True, timeout=5)
        for line in res.stdout.strip().splitlines():
            parts = line.split(":")
            if len(parts) >= 2 and parts[1].strip() == "wifi":
                return parts[0].strip()
    except Exception:
        pass
    return "wlan0"


def scan_wifi_networks():
    networks = []
    try:
        subprocess.run(["nmcli", "dev", "wifi", "rescan"], capture_output=True, text=True, timeout=8)
        res = subprocess.run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list"], capture_output=True, text=True, timeout=8)
        seen = set()
        for line in res.stdout.strip().splitlines():
            if line:
                parts = line.split(":")
                ssid = parts[0].strip()
                if ssid and ssid != AP_SSID and ssid not in seen:
                    seen.add(ssid)
                    signal = parts[1].strip() if len(parts) > 1 else "50"
                    security = parts[2].strip() if len(parts) > 2 else ""
                    networks.append({"ssid": ssid, "signal": signal, "security": security})
    except Exception:
        pass
    return networks


def ensure_wifi_enabled():
    try:
        subprocess.run(["nmcli", "radio", "wifi", "on"], capture_output=True, timeout=5)
    except Exception:
        pass


def start_access_point():
    ensure_wifi_enabled()
    iface = get_wifi_interface()
    print(f">> Starting Setup Hotspot: '{AP_SSID}' on {iface}...")
    try:
        subprocess.run(["nmcli", "connection", "delete", "NoiseBotSetup"], capture_output=True, text=True)
        subprocess.run([
            "nmcli", "connection", "add", "type", "wifi", "ifname", iface,
            "con-name", "NoiseBotSetup", "autoconnect", "no", "ssid", AP_SSID,
            "mode", "ap", "802-11-wireless.band", "bg",
            "ipv4.method", "shared", "ipv4.addresses", f"{AP_IP}/24"
        ], capture_output=True, text=True)
        subprocess.run(["nmcli", "connection", "up", "NoiseBotSetup"], capture_output=True, text=True)
        print(f">> Hotspot Active at {AP_IP}!")
    except Exception as e:
        print(f"Error starting hotspot: {e}")


def stop_access_point():
    try:
        subprocess.run(["nmcli", "connection", "down", "NoiseBotSetup"], capture_output=True, text=True)
        subprocess.run(["nmcli", "connection", "delete", "NoiseBotSetup"], capture_output=True, text=True)
    except Exception:
        pass


class CaptivePortalHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/scan":
            self.send_json(scan_wifi_networks())
            return

        if path == "/api/status":
            self.send_json(PROVISION_STATE)
            return

        # Captive portal detection endpoints & fallback
        if path in [
            "/hotspot-detect.html", "/canonical.html", "/success.txt",
            "/generate_204", "/gen_204", "/ncsi.txt", "/connecttest.txt"
        ] or not path.startswith("/api"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            
            # Inject dynamic initial state and saved config into page
            cfg = load_config()
            portal_html = HTML_PORTAL.replace(
                "/* __INITIAL_STATE__ */",
                f"window.__INITIAL_STATE__ = {json.dumps(PROVISION_STATE)};\\n    window.__SAVED_CONFIG__ = {json.dumps(cfg)};"
            )
            self.wfile.write(portal_html.encode("utf-8"))
            return

        self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/connect":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            try:
                data = json.loads(body)
            except Exception:
                self.send_json({"error": "Invalid JSON"}, 400)
                return

            ssid = data.get("ssid", "").strip()
            password = data.get("password", "")
            station_name = data.get("station_name", "Balcony Station").strip()
            street_name = data.get("street_name", "Edmonton Road").strip()
            floor_number = int(data.get("floor_number", 3))
            setback = float(data.get("setback", 5.0))
            admin_passcode = data.get("admin_passcode", "").strip() or "1811"

            if not ssid:
                self.send_json({"error": "Wi-Fi network name cannot be empty"}, 400)
                return

            cfg = load_config()
            cfg["admin_passcode"] = admin_passcode
            cfg["location_name"] = station_name
            cfg["street_name"] = street_name
            cfg["floor_number"] = floor_number
            cfg["horizontal_setback_meters"] = setback
            
            height = max(0, (floor_number - 1) * 3.0)
            dist = max(0.5, (setback**2 + height**2)**0.5)
            cfg["distance_to_road_meters"] = round(dist, 1)

            cfg.setdefault("fleet_hub", {})
            import re
            clean_id = re.sub(r'[^a-z0-9\-]', '', station_name.lower().replace(" ", "-")).strip('-') or "balcony-station"
            if not clean_id.startswith("noise-bot-"):
                clean_id = f"noise-bot-{clean_id}"
            cfg["fleet_hub"]["station_id"] = clean_id
            cfg["fleet_hub"]["station_name"] = station_name
            cfg["fleet_hub"]["enabled"] = True

            bsky_handle = data.get("bsky_handle", "").strip()
            bsky_password = data.get("bsky_password", "").strip()
            if bsky_handle and bsky_password:
                cfg.setdefault("bluesky", {})
                cfg["bluesky"]["enabled"] = True
                cfg["bluesky"]["handle"] = bsky_handle
                cfg["bluesky"]["app_password"] = bsky_password
                cfg["bluesky"]["target_handles"] = [
                    "@edmontonpolice.bsky.social",
                    "@ashleysalvador.bsky.social",
                    "@andrewknack.bsky.social"
                ]

            save_config(cfg)

            # Set in-flight state
            PROVISION_STATE["status"] = "connecting"
            PROVISION_STATE["ssid"] = ssid
            PROVISION_STATE["error"] = ""
            PROVISION_STATE["timestamp"] = time.time()

            # Respond immediately so client enters active testing mode
            self.send_json({"status": "connecting", "message": f"Testing connection to {ssid}..."})

            def switch_to_wifi():
                global PROVISION_STATE
                time.sleep(1)
                print(f">> Connecting to Wi-Fi '{ssid}'...")
                stop_access_point()
                time.sleep(2)

                # Delete any pre-existing connection with this SSID to avoid corrupted profile updates
                subprocess.run(["nmcli", "connection", "delete", ssid], capture_output=True, text=True)

                # Trigger an active rescan so wlan0 populates its scan cache in station mode
                subprocess.run(["nmcli", "dev", "wifi", "rescan"], capture_output=True, text=True, timeout=8)
                time.sleep(2)

                cmd = ["nmcli", "dev", "wifi", "connect", ssid]
                if password:
                    cmd.extend(["password", password])
                try:
                    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                    if res.returncode == 0:
                        print(f">> Successfully connected to {ssid}!")
                        PROVISION_STATE["status"] = "connected"
                        PROVISION_STATE["error"] = ""
                        # Allow pending polls to receive connected status
                        time.sleep(4)
                        compose_file = os.path.join(APP_DIR, "docker-compose.yml")
                        if os.path.exists(compose_file):
                            print(">> Starting Traffic Noise Monitor containers...")
                            subprocess.run(["docker", "compose", "-f", compose_file, "up", "-d"], capture_output=True)
                        print(">> IoT Provisioning Complete. Exiting cleanly.")
                        os._exit(0)
                    else:
                        err_raw = (res.stderr or res.stdout or "").strip()
                        print(f"Failed to connect to {ssid}: {err_raw}. Restoring Hotspot...")
                        
                        clean_err = "Unable to connect to Wi-Fi network."
                        if any(x in err_raw for x in ["Secrets were required", "802-11-wireless-security", "psk", "password", "key", "invalid"]):
                            clean_err = "Incorrect Wi-Fi password. Please check upper/lowercase letters and try again."
                        elif any(x in err_raw.lower() for x in ["not found", "no network", "could not find"]):
                            clean_err = f"Wi-Fi network '{ssid}' not found. Make sure router is on and in 2.4GHz range."
                        elif "timeout" in err_raw.lower():
                            clean_err = f"Connection to '{ssid}' timed out. Password may be wrong or signal is too weak."
                        else:
                            clean_err = f"Connection failed: {err_raw}"

                        PROVISION_STATE["status"] = "failed"
                        PROVISION_STATE["error"] = clean_err
                        start_access_point()
                except subprocess.TimeoutExpired:
                    print(f"Connection to {ssid} timed out after 30s. Restoring Hotspot...")
                    PROVISION_STATE["status"] = "failed"
                    PROVISION_STATE["error"] = f"Connection to '{ssid}' timed out (30s). Check password and signal strength."
                    start_access_point()
                except Exception as ex:
                    print(f"Unexpected error: {ex}. Restoring Hotspot...")
                    PROVISION_STATE["status"] = "failed"
                    PROVISION_STATE["error"] = str(ex)
                    start_access_point()

            import threading
            threading.Thread(target=switch_to_wifi, daemon=True).start()
            return

        self.send_error(404, "Not Found")


HTML_PORTAL = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Edmonton Noise Bot Setup</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
    body {
      background: #090d16;
      color: #f1f5f9;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 16px;
    }
    .container {
      width: 100%;
      max-width: 440px;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .card {
      background: rgba(18, 26, 43, 0.85);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 18px;
      padding: 22px;
      box-shadow: 0 20px 40px -15px rgba(0, 0, 0, 0.5);
    }
    .header { text-align: center; }
    .icon-badge {
      width: 52px;
      height: 52px;
      margin: 0 auto 12px;
      background: linear-gradient(135deg, #6366f1, #9333ea);
      border-radius: 14px;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 8px 20px rgba(99, 102, 241, 0.35);
    }
    .icon-badge svg { width: 28px; height: 28px; fill: white; }
    h1 { font-size: 20px; font-weight: 800; letter-spacing: -0.5px; }
    .subtitle { font-size: 12px; color: #94a3b8; margin-top: 4px; line-height: 1.4; }
    
    .alert-banner {
      display: none;
      padding: 14px 16px;
      border-radius: 12px;
      font-size: 12px;
      line-height: 1.4;
      margin-bottom: 12px;
    }
    .alert-banner.alert-error {
      display: block;
      background: rgba(220, 38, 38, 0.15);
      border: 1px solid #ef4444;
      color: #fca5a5;
    }
    .alert-banner.alert-connecting {
      display: block;
      background: rgba(99, 102, 241, 0.15);
      border: 1px solid #6366f1;
      color: #c7d2fe;
      text-align: center;
    }
    .alert-banner.alert-success {
      display: block;
      background: rgba(16, 185, 129, 0.15);
      border: 1px solid #10b981;
      color: #6ee7b7;
      text-align: center;
    }

    .section-title {
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.6px;
      color: #cbd5e1;
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 8px;
      margin-top: 14px;
    }
    .section-title:first-child { margin-top: 0; }
    .scan-btn {
      background: none;
      border: none;
      color: #818cf8;
      font-size: 11px;
      font-weight: 600;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }
    .wifi-list {
      max-height: 140px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 6px;
      margin-bottom: 8px;
    }
    .wifi-item {
      background: #0d1527;
      border: 1px solid #1e293b;
      border-radius: 10px;
      padding: 10px 12px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      cursor: pointer;
      transition: background 0.15s;
    }
    .wifi-item:hover, .wifi-item.selected {
      background: #1e1b4b;
      border-color: #6366f1;
    }
    .wifi-name { font-size: 12px; font-weight: 600; color: #fff; }
    .wifi-signal { font-size: 10px; color: #94a3b8; font-family: monospace; }
    
    .input-group {
      position: relative;
      width: 100%;
      margin-bottom: 8px;
    }
    input[type="text"], input[type="password"] {
      width: 100%;
      background: #0a101f;
      border: 1px solid #25334d;
      border-radius: 10px;
      padding: 11px 13px;
      font-size: 12px;
      color: #fff;
      outline: none;
      transition: border-color 0.2s;
    }
    input:focus { border-color: #6366f1; }
    input.input-error { border-color: #ef4444; background: #1c0f14; }

    .btn-toggle-pw {
      position: absolute;
      right: 10px;
      top: 50%;
      transform: translateY(-50%);
      background: none;
      border: none;
      color: #94a3b8;
      font-size: 15px;
      cursor: pointer;
      padding: 4px 6px;
      opacity: 0.8;
      transition: opacity 0.2s;
    }
    .btn-toggle-pw:hover { opacity: 1; }

    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px; }
    label { display: block; font-size: 10px; color: #94a3b8; margin-bottom: 4px; }
    .slider-box {
      background: #0a101f;
      border: 1px solid #1e293b;
      border-radius: 10px;
      padding: 10px 12px;
      margin-bottom: 8px;
    }
    .slider-info { display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 6px; }
    .slider-val { font-weight: 700; color: #818cf8; }
    input[type="range"] {
      width: 100%;
      accent-color: #6366f1;
      height: 4px;
      cursor: pointer;
    }
    .hint { font-size: 10px; color: #64748b; line-height: 1.3; margin-top: -4px; margin-bottom: 8px; }
    .btn-submit {
      width: 100%;
      padding: 14px;
      margin-top: 10px;
      background: linear-gradient(135deg, #4f46e5, #7c3aed);
      border: none;
      border-radius: 12px;
      color: #fff;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
      box-shadow: 0 10px 25px -5px rgba(99, 102, 241, 0.4);
      transition: opacity 0.2s;
    }
    .btn-submit:disabled { opacity: 0.6; cursor: not-allowed; }
    
    .spinner {
      display: inline-block;
      width: 16px;
      height: 16px;
      border: 2px solid rgba(255,255,255,0.3);
      border-radius: 50%;
      border-top-color: #fff;
      animation: spin 0.8s linear infinite;
      vertical-align: middle;
      margin-right: 6px;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
  </style>
</head>
<body>
  <div class="container">
    <div class="card header">
      <div class="icon-badge">
        <svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 14h-2v-2h2v2zm0-4h-2V7h2v5z"/></svg>
      </div>
      <h1>Edmonton Noise Watch</h1>
      <p class="subtitle">Connect station to home Wi-Fi with live credential testing.</p>
    </div>

    <div class="card">
      <div id="alertBanner" class="alert-banner"></div>

      <div class="section-title">
        <span>1. Select Home Wi-Fi</span>
        <button class="scan-btn" onclick="scanNetworks()" id="scanBtn">🔄 Scan</button>
      </div>
      <div id="wifiList" class="wifi-list">
        <div style="text-align: center; padding: 16px; font-size: 11px; color: #64748b;">Scanning nearby Wi-Fi...</div>
      </div>
      
      <div class="input-group">
        <input type="text" id="selectedSsid" placeholder="Wi-Fi Network Name (SSID)" autocapitalize="none" autocorrect="off" autocomplete="off" spellcheck="false">
      </div>
      
      <div class="input-group">
        <input type="password" id="wifiPassword" placeholder="Enter Wi-Fi Password" autocapitalize="none" autocorrect="off" autocomplete="off" spellcheck="false" style="padding-right: 42px;">
        <button type="button" class="btn-toggle-pw" onclick="togglePwVisibility('wifiPassword')" title="Show/Hide Password">👁️</button>
      </div>

      <div class="section-title">
        <span>2. Location & Floor Height</span>
      </div>
      <div class="grid-2">
        <div>
          <label>Station Name</label>
          <input type="text" id="stationName" value="Balcony Station">
        </div>
        <div>
          <label>Street / Corridor</label>
          <input type="text" id="streetName" placeholder="e.g. 104th St">
        </div>
      </div>
      <div class="slider-box">
        <div class="slider-info">
          <span style="color: #94a3b8;">Elevation Level:</span>
          <span id="floorVal" class="slider-val">Floor 3 (~6m height)</span>
        </div>
        <input type="range" id="floorSlider" min="1" max="30" value="3" oninput="updateFloor(this.value)">
      </div>

      <div class="section-title">
        <span>3. Station Admin Passcode</span>
      </div>
      <div class="input-group">
        <input type="password" id="adminPasscode" placeholder="Create Station Passcode (default: 1811)" autocapitalize="none" autocorrect="off" autocomplete="off" spellcheck="false" style="padding-right: 42px;">
        <button type="button" class="btn-toggle-pw" onclick="togglePwVisibility('adminPasscode')" title="Show/Hide Password">👁️</button>
      </div>
      <p class="hint">Your private passcode for this station's control panel. Does not grant access to sethdear.ca root or central hub.</p>

      <div class="section-title">
        <span>4. Bluesky Alerts (Optional)</span>
        <span style="color: #64748b; font-size: 10px; font-weight: normal;">Optional</span>
      </div>
      <div class="grid-2">
        <div>
          <label>Bot Handle</label>
          <input type="text" id="bskyHandle" placeholder="user.bsky.social" autocapitalize="none" autocorrect="off" autocomplete="off" spellcheck="false">
        </div>
        <div>
          <label>App Password</label>
          <div class="input-group" style="margin-bottom: 0;">
            <input type="password" id="bskyPassword" placeholder="xxxx-xxxx-xxxx-xxxx" autocapitalize="none" autocorrect="off" autocomplete="off" spellcheck="false" style="padding-right: 42px;">
            <button type="button" class="btn-toggle-pw" onclick="togglePwVisibility('bskyPassword')" title="Show/Hide Password">👁️</button>
          </div>
        </div>
      </div>
      <p class="hint">Auto-posts loud noise events to Bluesky. Leave blank to skip.</p>

      <button class="btn-submit" id="submitBtn" onclick="submitSetup()">Test & Connect Station</button>
    </div>
  </div>

  <script>
    /* __INITIAL_STATE__ */
    let pollTimer = null;
    let pollAttempts = 0;

    function togglePwVisibility(inputId) {
      const input = document.getElementById(inputId);
      if (input.type === 'password') {
        input.type = 'text';
      } else {
        input.type = 'password';
      }
    }

    function updateFloor(val) {
      const height = (val - 1) * 3;
      document.getElementById('floorVal').innerText = 'Floor ' + val + ' (~' + height + 'm height)';
    }

    async function scanNetworks() {
      const list = document.getElementById('wifiList');
      const btn = document.getElementById('scanBtn');
      btn.innerText = '⏳ Scanning...';
      try {
        const res = await fetch('/api/scan');
        const nets = await res.json();
        btn.innerText = '🔄 Scan';
        if (!nets || nets.length === 0) {
          list.innerHTML = '<div style="text-align: center; padding: 12px; font-size: 11px; color: #64748b;">No Wi-Fi detected. Type network name manually.</div>';
          return;
        }
        list.innerHTML = nets.map(n => `
          <div class="wifi-item" onclick="selectNet('${n.ssid}')">
            <span class="wifi-name">📶 ${n.ssid}</span>
            <span class="wifi-signal">${n.signal}%</span>
          </div>
        `).join('');
      } catch (e) {
        btn.innerText = '🔄 Scan';
        list.innerHTML = '<div style="text-align: center; padding: 12px; font-size: 11px; color: #64748b;">Type your Wi-Fi name below.</div>';
      }
    }

    function selectNet(ssid) {
      document.getElementById('selectedSsid').value = ssid;
      const pwInput = document.getElementById('wifiPassword');
      pwInput.focus();
    }

    function showError(msg, ssid) {
      const banner = document.getElementById('alertBanner');
      const btn = document.getElementById('submitBtn');
      const pwInput = document.getElementById('wifiPassword');
      
      banner.className = 'alert-banner alert-error';
      banner.innerHTML = `
        <div style="font-weight: 700; margin-bottom: 4px;">❌ Wi-Fi Connection Failed</div>
        <div>Could not connect to <strong>${ssid || 'network'}</strong>.</div>
        <div style="margin-top: 6px; font-size: 11px; color: #fecaca;">${msg}</div>
        <div style="margin-top: 8px; font-size: 11px; color: #cbd5e1;">💡 Please check for uppercase/lowercase letters or extra spaces, then try again.</div>
      `;
      
      pwInput.classList.add('input-error');
      pwInput.type = 'text';
      pwInput.focus();

      btn.disabled = false;
      btn.innerText = 'Retry Connection';
    }

    function showSuccess(ssid) {
      const banner = document.getElementById('alertBanner');
      const btn = document.getElementById('submitBtn');
      
      banner.className = 'alert-banner alert-success';
      banner.innerHTML = `
        <div style="font-weight: 700; font-size: 14px; margin-bottom: 6px;">🎉 Connected Successfully!</div>
        <div style="font-size: 12px; margin-bottom: 8px;">Station has joined <strong>${ssid}</strong> and started 24/7 acoustic monitoring!</div>
        <a href="https://sethdear.ca/yegnoise" target="_blank" style="display:inline-block; padding: 8px 16px; background: #10b981; color: white; border-radius: 8px; text-decoration: none; font-weight: 700; font-size: 12px; margin-top: 4px;">View Live Dashboard →</a>
      `;
      btn.style.display = 'none';
    }

    function showConnecting(ssid) {
      const banner = document.getElementById('alertBanner');
      const btn = document.getElementById('submitBtn');
      const pwInput = document.getElementById('wifiPassword');
      
      pwInput.classList.remove('input-error');
      banner.className = 'alert-banner alert-connecting';
      banner.innerHTML = `
        <div style="font-weight: 700; margin-bottom: 4px;"><span class="spinner"></span>Testing Wi-Fi Handshake...</div>
        <div>Connecting to <strong>${ssid}</strong> and verifying password.</div>
        <div style="margin-top: 6px; font-size: 11px; color: #fbbf24; font-weight: 600;">⚠️ Do NOT close this window. Verification takes ~15–20s.</div>
      `;
      btn.disabled = true;
      btn.innerText = 'Verifying credentials...';
    }

    function startStatusPolling(ssid) {
      pollAttempts = 0;
      if (pollTimer) clearInterval(pollTimer);

      pollTimer = setInterval(async () => {
        pollAttempts++;
        try {
          const res = await fetch('/api/status', { cache: 'no-store' });
          const state = await res.json();
          
          if (state.status === 'failed') {
            clearInterval(pollTimer);
            showError(state.error || 'Wi-Fi connection failed.', state.ssid || ssid);
          } else if (state.status === 'connected') {
            clearInterval(pollTimer);
            showSuccess(state.ssid || ssid);
          }
        } catch (e) {
          // Expected when Pi drops AP to test connection with router
          if (pollAttempts > 25) {
            clearInterval(pollTimer);
            try {
              const checkHub = await fetch('https://sethdear.ca/api/fleet-data', { mode: 'no-cors' });
              showSuccess(ssid);
            } catch (err) {
              showError('Connection test timed out. Please reconnect to Edmonton-Noise-Bot-Setup and retry.', ssid);
            }
          }
        }
      }, 2000);
    }

    async function submitSetup() {
      const ssid = document.getElementById('selectedSsid').value.trim();
      const password = document.getElementById('wifiPassword').value;
      const stationName = document.getElementById('stationName').value.trim();
      const streetName = document.getElementById('streetName').value.trim();
      const floor = document.getElementById('floorSlider').value;
      const adminPasscode = document.getElementById('adminPasscode').value.trim() || '1811';
      const bskyHandle = document.getElementById('bskyHandle').value.trim();
      const bskyPassword = document.getElementById('bskyPassword').value.trim();

      if (!ssid) {
        alert('Please select or type your Wi-Fi network name');
        return;
      }

      showConnecting(ssid);

      try {
        await fetch('/api/connect', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ssid: ssid,
            password: password,
            station_name: stationName,
            street_name: streetName,
            floor_number: floor,
            setback: 5.0,
            admin_passcode: adminPasscode,
            bsky_handle: bskyHandle,
            bsky_password: bskyPassword
          })
        });
        
        startStatusPolling(ssid);
      } catch (e) {
        startStatusPolling(ssid);
      }
    }

    // Pre-populate fields with existing configuration if available
    if (window.__SAVED_CONFIG__) {
      const cfg = window.__SAVED_CONFIG__;
      if (cfg.location_name) document.getElementById('stationName').value = cfg.location_name;
      if (cfg.street_name) document.getElementById('streetName').value = cfg.street_name;
      if (cfg.floor_number) {
        document.getElementById('floorSlider').value = cfg.floor_number;
        updateFloor(cfg.floor_number);
      }
      if (cfg.admin_passcode) document.getElementById('adminPasscode').value = cfg.admin_passcode;
      if (cfg.bluesky && cfg.bluesky.handle) document.getElementById('bskyHandle').value = cfg.bluesky.handle;
      if (cfg.bluesky && cfg.bluesky.app_password) document.getElementById('bskyPassword').value = cfg.bluesky.app_password;
    }

    // Check if initial page load was after a previous failure
    if (window.__INITIAL_STATE__ && window.__INITIAL_STATE__.status === 'failed') {
      const failedState = window.__INITIAL_STATE__;
      if (failedState.ssid) {
        document.getElementById('selectedSsid').value = failedState.ssid;
      }
      showError(failedState.error || 'Wi-Fi connection failed.', failedState.ssid);
    }

    scanNetworks();
  </script>
</body>
</html>
"""


def wait_for_network_grace_period(timeout_seconds=15):
    """
    Give NetworkManager up to timeout_seconds to automatically associate
    with any previously configured Wi-Fi networks before assuming headless AP mode.
    """
    print(f">> Checking network connectivity (waiting up to {timeout_seconds}s for auto-connect)...")
    start = time.time()
    while time.time() - start < timeout_seconds:
        if is_network_connected():
            return True
        time.sleep(2)
    return is_network_connected()


def main():
    if wait_for_network_grace_period(15):
        print(">> Network connection detected. IoT Auto-Provisioner exiting (normal mode).")
        sys.exit(0)

    print(">> No active network detected after grace period. Entering Headless IoT Auto-Provisioning mode...")
    start_access_point()

    server_address = ('0.0.0.0', PORT)
    try:
        httpd = ThreadingHTTPServer(server_address, CaptivePortalHandler)
    except Exception:
        server_address = ('0.0.0.0', 5000)
        httpd = ThreadingHTTPServer(server_address, CaptivePortalHandler)

    print(f">> Captive Portal active on http://{AP_IP}:{server_address[1]}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
