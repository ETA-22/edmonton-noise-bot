import os
import re
import sys
import json
import time
import math
import subprocess
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "v1.2.0"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RECORDINGS_DIR = os.path.join(BASE_DIR, "recordings")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
CONFIG_EXAMPLE_FILE = os.path.join(BASE_DIR, "config.example.json")
LIVE_STATE_FILE = os.path.join(BASE_DIR, "live_audio_state.json")
LOG_FILE = os.path.join(BASE_DIR, "noise_bot.log")
FLEET_DB_FILE = os.path.join(BASE_DIR, "fleet_database.json")

ALLOWED_TAGS = ["traffic", "vehicle", "weather", "siren", "construction", "misc", "review"]

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    if os.path.exists(CONFIG_EXAMPLE_FILE):
        try:
            with open(CONFIG_EXAMPLE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "admin_passcode": "admin123",
        "location_name": "Balcony",
        "street_name": "98th Ave",
        "floor_number": 3,
        "horizontal_setback_meters": 5.0,
        "distance_to_road_meters": 10.3,
        "threshold_dba": 75.0,
        "calibration_offset": 50.0
    }

def save_config(new_config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(new_config, f, indent=2)

def load_fleet_db():
    if os.path.exists(FLEET_DB_FILE):
        try:
            with open(FLEET_DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "stations": {},
        "recent_violations": []
    }

def save_fleet_db(db):
    try:
        with open(FLEET_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2)
    except Exception as e:
        print(f"Error saving fleet DB: {e}")

def is_admin(parsed_url, headers=None):
    cfg = load_config()
    expected = cfg.get("admin_passcode", "admin123")
    query = urllib.parse.parse_qs(parsed_url.query)
    key = query.get("key", [""])[0]
    if key == expected:
        return True
    if headers:
        auth_hdr = headers.get("X-Admin-Key", "")
        if auth_hdr == expected:
            return True
    return False

def get_audio_devices():
    devs = []
    # 1. Read Linux ALSA kernel cards directly (never blocked by EBUSY)
    if os.path.exists("/proc/asound/cards"):
        try:
            with open("/proc/asound/cards", "r") as f:
                content = f.read()
            import re
            card_matches = re.findall(r"^\s*(\d+)\s*\[([^\]]+)\]:\s*([^\n-]+)(?:-\s*([^\n]+))?", content, re.MULTILINE)
            for m in card_matches:
                card_idx = int(m[0])
                card_name = (m[3].strip() if m[3] else m[2].strip())
                if "headphone" not in card_name.lower() and "vc4" not in card_name.lower():
                    devs.append({
                        "index": card_idx,
                        "name": f"{card_name} (hw:{card_idx},0)",
                        "channels": 2
                    })
        except Exception:
            pass

    # 2. PyAudio enumeration
    if not devs:
        try:
            import pyaudio
            p = pyaudio.PyAudio()
            info = p.get_host_api_info_by_index(0)
            numdevices = info.get('deviceCount', 0)
            for i in range(0, numdevices):
                try:
                    device_info = p.get_device_info_by_host_api_device_index(0, i)
                    if device_info.get('maxInputChannels', 0) > 0:
                        devs.append({
                            "index": i,
                            "name": device_info.get('name'),
                            "channels": device_info.get('maxInputChannels')
                        })
                except Exception:
                    pass
            p.terminate()
        except Exception:
            pass

    if not devs:
        devs.append({"index": 1, "name": "USB Microphone (hw:1,0)", "channels": 2})

    return devs

class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Station-ID, X-Admin-Key")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Station-ID, X-Admin-Key")
        self.end_headers()

    def get_events(self):
        events = []
        if not os.path.exists(RECORDINGS_DIR):
            return events

        pattern = re.compile(r"noise_event_(\d{8})_(\d{6})_(\d+)dba_?([a-zA-Z0-9_-]*)\.wav")
        for filename in os.listdir(RECORDINGS_DIR):
            match = pattern.match(filename)
            if match:
                date_str, time_str, dba_str, tag_str = match.groups()
                tag = tag_str.lower() if tag_str else "review"
                if tag == "vehicle":
                    tag = "traffic"
                dt_iso = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}T{time_str[:2]}:{time_str[2:4]}:{time_str[4:]}"
                file_path = os.path.join(RECORDINGS_DIR, filename)
                events.append({
                    "filename": filename,
                    "date": f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}",
                    "time": f"{time_str[:2]}:{time_str[2:4]}:{time_str[4:]}",
                    "datetime": dt_iso,
                    "dba": int(dba_str),
                    "tag": tag,
                    "size": os.path.getsize(file_path) if os.path.exists(file_path) else 0,
                    "url": f"/recordings/{filename}"
                })
        events.sort(key=lambda x: x["datetime"], reverse=True)
        return events

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path == "/api/events":
            self.send_json(self.get_events())
            return

        elif path == "/api/audio-devices":
            self.send_json(get_audio_devices())
            return

        elif path == "/api/live-level":
            if os.path.exists(LIVE_STATE_FILE):
                try:
                    with open(LIVE_STATE_FILE, "r") as f:
                        data = json.load(f)
                    self.send_json(data)
                    return
                except Exception:
                    pass
            self.send_json({"current_dba": 0.0, "is_recording": False, "timestamp": time.time()})
            return

        elif path == "/api/fleet-data":
            db = load_fleet_db()
            now = time.time()
            stations_list = []
            
            # Always ensure local station is present in fleet list
            cfg = load_config()
            local_live_dba = 0.0
            if os.path.exists(LIVE_STATE_FILE):
                try:
                    with open(LIVE_STATE_FILE, "r") as f:
                        local_live_dba = json.load(f).get("current_dba", 0.0)
                except Exception:
                    pass

            local_station_id = "local-balcony"
            db.setdefault("stations", {})
            db["stations"][local_station_id] = {
                "station_id": local_station_id,
                "station_name": f"{cfg.get('location_name', 'Balcony')} (Host Pi)",
                "street_name": cfg.get("street_name", "98th Ave"),
                "location_name": cfg.get("location_name", "Balcony"),
                "floor_number": cfg.get("floor_number", 3),
                "distance_to_road_meters": cfg.get("distance_to_road_meters", 7.8),
                "current_dba": local_live_dba,
                "last_peak_dba": 0.0,
                "total_violations": len(self.get_events()),
                "version": VERSION,
                "last_seen": now
            }

            for s_id, s_data in db.get("stations", {}).items():
                last_seen = s_data.get("last_seen", 0)
                diff_sec = now - last_seen
                is_online = diff_sec < 60
                stations_list.append({
                    **s_data,
                    "id": s_id,
                    "is_online": is_online,
                    "seconds_since_ping": int(diff_sec)
                })
            
            self.send_json({
                "stations": stations_list,
                "recent_violations": db.get("recent_violations", [])[-30:],
                "server_time": now
            })
            return

        elif path == "/api/config":
            if not is_admin(parsed_url, self.headers):
                self.send_json({"error": "Unauthorized"}, 403)
                return
            self.send_json(load_config())
            return

        elif path == "/api/wifi/scan":
            networks = []
            try:
                res = subprocess.run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list"], capture_output=True, text=True, timeout=5)
                for line in res.stdout.strip().split("\n"):
                    if line:
                        parts = line.split(":")
                        if len(parts) >= 2 and parts[0]:
                            networks.append({"ssid": parts[0], "signal": parts[1], "security": parts[2] if len(parts) > 2 else ""})
            except Exception:
                pass
            
            if not networks:
                try:
                    res2 = subprocess.run(["iwlist", "wlan0", "scan"], capture_output=True, text=True, timeout=5)
                    import re
                    ssids = re.findall(r'ESSID:"([^"]+)"', res2.stdout)
                    for s in set(ssids):
                        if s:
                            networks.append({"ssid": s, "signal": "85", "security": "WPA2"})
                except Exception:
                    pass

            self.send_json(networks)
            return

        elif path == "/api/logs":
            if not is_admin(parsed_url, self.headers):
                self.send_json({"error": "Unauthorized"}, 403)
                return
            logs = ""
            if os.path.exists(LOG_FILE):
                try:
                    with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                        logs = "".join(lines[-100:])
                except Exception as e:
                    logs = f"Error reading logs: {e}"
            self.send_json({"logs": logs})
            return

        elif path.startswith("/recordings/"):
            filename = os.path.basename(path)
            file_path = os.path.join(RECORDINGS_DIR, filename)
            if os.path.exists(file_path) and filename.endswith(".wav"):
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(os.path.getsize(file_path)))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                with open(file_path, "rb") as f:
                    self.wfile.write(f.read())
                return
            else:
                self.send_error(404, "File not found")
                return

        elif path in ["/", "/index.html", "/settings"]:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = HTML_DASHBOARD.replace("__VERSION__", VERSION)
            self.wfile.write(html.encode("utf-8"))
            return

        elif path in ["/fleet", "/fleet.html"]:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_FLEET.encode("utf-8"))
            return

        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path in ["/api/heartbeat", "/api/fleet/heartbeat"]:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            try:
                payload = json.loads(body)
                station_id = payload.get("station_id") or payload.get("location_name", "unknown")
                station_id = str(station_id).lower().replace(" ", "-")

                db = load_fleet_db()
                now = time.time()
                
                station_info = db.get("stations", {}).get(station_id, {})
                station_info.update({
                    "station_id": station_id,
                    "station_name": payload.get("station_name") or payload.get("location_name") or "Station",
                    "street_name": payload.get("street_name", "Edmonton Road"),
                    "location_name": payload.get("location_name", "Balcony"),
                    "floor_number": payload.get("floor_number", 1),
                    "distance_to_road_meters": payload.get("distance_to_road_meters", 10.0),
                    "current_dba": float(payload.get("current_dba", 0.0)),
                    "last_peak_dba": float(payload.get("last_peak_dba", 0.0)),
                    "total_violations": int(payload.get("total_violations", 0)),
                    "version": payload.get("version", "v1.2.0"),
                    "last_seen": now
                })

                if "history" not in station_info:
                    station_info["history"] = []
                
                station_info["history"].append({
                    "time": time.strftime("%H:%M"),
                    "dba": station_info["current_dba"]
                })
                station_info["history"] = station_info["history"][-20:]

                db["stations"][station_id] = station_info

                if payload.get("event"):
                    ev = payload.get("event")
                    db["recent_violations"].append({
                        "station_id": station_id,
                        "station_name": station_info["station_name"],
                        "street_name": station_info["street_name"],
                        "dba": ev.get("dba"),
                        "tailpipe_dba": ev.get("tailpipe_dba"),
                        "tag": ev.get("tag", "traffic"),
                        "time_str": time.strftime("%I:%M %p"),
                        "timestamp": now
                    })
                    db["recent_violations"] = db["recent_violations"][-50:]

                save_fleet_db(db)
                self.send_json({"success": True, "station_id": station_id})
            except Exception as e:
                self.send_json({"error": str(e)}, 400)
            return

        elif path.startswith("/api/reclassify/"):
            filename = os.path.basename(path)
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            data = json.loads(body)
            new_tag = data.get("tag", "").lower().strip()
            if not new_tag:
                self.send_json({"error": "Missing tag"}, 400)
                return

            pattern = re.compile(r"noise_event_(\d{8})_(\d{6})_(\d+)dba_?([a-zA-Z0-9_-]*)\.wav")
            match = pattern.match(filename)
            if not match:
                self.send_json({"error": "Invalid filename format"}, 400)
                return

            date_str, time_str, dba_str, _ = match.groups()
            old_path = os.path.join(RECORDINGS_DIR, filename)
            new_filename = f"noise_event_{date_str}_{time_str}_{dba_str}dba_{new_tag}.wav"
            new_path = os.path.join(RECORDINGS_DIR, new_filename)

            if os.path.exists(old_path):
                try:
                    os.rename(old_path, new_path)
                    self.send_json({"success": True, "new_filename": new_filename, "tag": new_tag})
                except Exception as e:
                    self.send_json({"error": f"Failed to rename file: {e}"}, 500)
            else:
                self.send_json({"error": "Original file not found"}, 404)
            return

        elif path == "/api/config":
            if not is_admin(parsed_url, self.headers):
                self.send_json({"error": "Unauthorized"}, 403)
                return
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            try:
                new_cfg = json.loads(body)
                save_config(new_cfg)
                try:
                    with open(os.path.join(BASE_DIR, ".reload_trigger"), "w") as f:
                        f.write(str(time.time()))
                except Exception:
                    pass
                self.send_json({"success": True, "message": "Configuration saved successfully!"})
            except Exception as e:
                self.send_json({"error": str(e)}, 400)
            return

        elif path.startswith("/api/delete/"):
            if not is_admin(parsed_url, self.headers):
                self.send_json({"error": "Unauthorized"}, 403)
                return
            filename = os.path.basename(path)
            file_path = os.path.join(RECORDINGS_DIR, filename)
            if os.path.exists(file_path) and filename.endswith(".wav"):
                try:
                    os.remove(file_path)
                    self.send_json({"success": True})
                except Exception as e:
                    self.send_json({"error": str(e)}, 500)
            else:
                self.send_json({"error": "File not found"}, 404)
            return

        elif path == "/api/wifi/connect":
            if not is_admin(parsed_url, self.headers):
                self.send_json({"error": "Unauthorized"}, 403)
                return
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            data = json.loads(body)
            ssid = data.get("ssid")
            password = data.get("password")
            try:
                cmd = ["nmcli", "dev", "wifi", "connect", ssid]
                if password:
                    cmd.extend(["password", password])
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                if res.returncode == 0:
                    self.send_json({"success": True, "message": f"Connected to {ssid}!"})
                else:
                    self.send_json({"success": False, "error": res.stderr}, 400)
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, 500)
            return

        elif path == "/api/restart-detector":
            if not is_admin(parsed_url, self.headers):
                self.send_json({"error": "Unauthorized"}, 403)
                return
            try:
                with open(os.path.join(BASE_DIR, ".reload_trigger"), "w") as f:
                    f.write(str(time.time()))
                self.send_json({"success": True, "message": "Audio detector reload triggered."})
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
            return

        else:
            self.send_error(404, "Not Found")

HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Edmonton Noise Bot Dashboard</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    body { background-color: #0f172a; color: #f8fafc; font-family: system-ui, -apple-system, sans-serif; }
    .glass-card { background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.08); }
    .meter-bar { transition: width 0.15s ease-out; }
  </style>
</head>
<body class="min-h-screen p-4 md:p-8 pb-24 md:pb-8">
  <div class="max-w-7xl mx-auto space-y-6">

    <!-- Header with Version in Top Right & Fleet Link -->
    <header class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 glass-card p-6 rounded-2xl shadow-xl">
      <div class="flex items-center gap-3">
        <div class="p-3 bg-indigo-600/20 text-indigo-400 rounded-xl text-2xl">
          <i class="fa-solid fa-volume-high"></i>
        </div>
        <div>
          <h1 class="text-2xl font-bold text-white tracking-tight">Traffic Noise Monitor</h1>
          <p id="headerSubtitle" class="text-sm text-slate-400">Live Acoustic Telemetry & Event Logger</p>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <a href="/fleet" class="px-3 py-1.5 bg-indigo-900/60 hover:bg-indigo-800/80 border border-indigo-500/40 text-indigo-300 font-bold text-xs rounded-xl flex items-center gap-1.5 transition">
          <i class="fa-solid fa-tower-broadcast"></i> City Fleet Hub
        </a>
        <span class="px-3 py-1.5 bg-slate-800/90 border border-slate-700/80 text-indigo-400 font-mono text-xs rounded-xl font-bold flex items-center gap-1.5 shadow-sm">
          <i class="fa-solid fa-code-branch text-[10px]"></i> __VERSION__
        </span>
        <button onclick="fetchEvents()" class="px-3.5 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-medium flex items-center gap-1.5 shadow-lg shadow-indigo-600/30 transition">
          <i class="fa-solid fa-arrows-rotate"></i> Refresh
        </button>
      </div>
    </header>

    <!-- TAB 1: LIVE VIEW -->
    <div id="viewLive" class="space-y-6">
      <!-- Real-time Live Meter Card -->
      <div class="glass-card p-6 rounded-2xl shadow-xl space-y-4">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="relative flex h-3 w-3">
              <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span class="relative inline-flex rounded-full h-3 w-3 bg-emerald-500"></span>
            </span>
            <h2 class="text-lg font-semibold text-white">Live Microphone Sound Pressure</h2>
          </div>
          <div class="flex items-center gap-3">
            <div class="text-right">
              <div class="flex items-center gap-1">
                <span id="liveDbaText" class="text-3xl font-black text-emerald-400">--</span>
                <span class="text-slate-400 font-semibold">dBA</span>
              </div>
              <div id="liveTailpipeText" class="text-xs text-slate-400 font-mono">Est. Tailpipe: -- dBA</div>
            </div>
          </div>
        </div>
        <div class="w-full bg-slate-800/80 rounded-full h-5 overflow-hidden p-0.5 border border-slate-700">
          <div id="liveMeterFill" class="meter-bar bg-gradient-to-r from-emerald-500 via-amber-500 to-rose-600 h-full rounded-full w-0"></div>
        </div>
        <div class="flex justify-between text-xs font-mono text-slate-500">
          <span>30 dBA (Quiet)</span>
          <span>65 dBA (Bylaw Limit)</span>
          <span>85 dBA (Loud Exhaust)</span>
          <span>110+ dBA (Extreme)</span>
        </div>
      </div>

      <!-- Quick Stats Grid -->
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div class="glass-card p-5 rounded-2xl">
          <div class="text-slate-400 text-sm font-medium">Total Events Recorded</div>
          <div id="statTotal" class="text-2xl font-bold text-white mt-1">0</div>
        </div>
        <div class="glass-card p-5 rounded-2xl">
          <div class="text-slate-400 text-sm font-medium">Traffic / Exhaust Noise</div>
          <div id="statVehicle" class="text-2xl font-bold text-indigo-400 mt-1">0</div>
        </div>
        <div class="glass-card p-5 rounded-2xl">
          <div class="text-slate-400 text-sm font-medium">Peak Decibel Recorded</div>
          <div id="statPeak" class="text-2xl font-bold text-rose-400 mt-1">-- dBA</div>
        </div>
        <div class="glass-card p-5 rounded-2xl">
          <div class="text-slate-400 text-sm font-medium">Bylaw Exceedances (>70 dBA)</div>
          <div id="statBylaw" class="text-2xl font-bold text-amber-400 mt-1">0</div>
        </div>
      </div>
    </div>

    <!-- TAB 2: STATS & CHARTS VIEW -->
    <div id="viewStats" class="space-y-6 hidden">
      <!-- Events Per Day Chart -->
      <div class="glass-card p-6 rounded-2xl shadow-xl space-y-4">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <i class="fa-solid fa-chart-column text-indigo-400 text-lg"></i>
            <h2 class="text-lg font-bold text-white">Daily Noise Events (Events per Day)</h2>
          </div>
          <span class="text-xs text-slate-400 font-mono">Past 14 Days</span>
        </div>
        <div class="h-64 w-full">
          <canvas id="dailyEventsChart"></canvas>
        </div>
      </div>
    </div>

    <!-- RECORDED AUDIO CLIPS LIST -->
    <div class="glass-card rounded-2xl shadow-xl overflow-hidden">
      <div class="p-6 border-b border-slate-800 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 class="text-xl font-bold text-white">Recorded Noise Clips</h2>
          <p class="text-xs text-slate-400">Change classification on the fly using the dropdown on any clip</p>
        </div>
        <div class="flex items-center gap-2">
          <select id="filterTag" onchange="renderEvents()" class="bg-slate-800 border border-slate-700 text-slate-300 text-sm rounded-xl px-3 py-2">
            <option value="all">All Events</option>
            <option value="traffic">🚗 Traffic / Vehicle</option>
            <option value="siren">🚨 Siren</option>
            <option value="construction">🏗️ Construction</option>
            <option value="weather">🌧️ Weather / Wind</option>
            <option value="misc">❓ Misc / Other</option>
            <option value="review">⚠️ Needs Review</option>
          </select>
        </div>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-left text-sm text-slate-300">
          <thead class="bg-slate-800/60 text-xs uppercase text-slate-400 tracking-wider">
            <tr>
              <th class="py-3 px-6">Timestamp</th>
              <th class="py-3 px-6">Sound Level</th>
              <th class="py-3 px-6">Classification</th>
              <th class="py-3 px-6">Audio Playback</th>
              <th class="py-3 px-6 text-right">Actions</th>
            </tr>
          </thead>
          <tbody id="eventsTableBody" class="divide-y divide-slate-800/40">
            <tr>
              <td colspan="5" class="py-8 text-center text-slate-500">Loading noise recordings...</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

  </div>

  <!-- Bottom Navigation Bar -->
  <nav class="fixed bottom-0 inset-x-0 bg-slate-900/95 backdrop-blur border-t border-slate-800 py-3 px-8 flex justify-around items-center z-40 select-none">
    <button onclick="switchMainTab('live')" id="navBtnLive" class="flex flex-col items-center gap-1 text-indigo-400 font-semibold text-xs transition">
      <i class="fa-solid fa-house text-base"></i>
      <span>Live</span>
    </button>
    <button onclick="switchMainTab('stats')" id="navBtnStats" class="flex flex-col items-center gap-1 text-slate-400 hover:text-white text-xs transition">
      <i class="fa-solid fa-chart-column text-base"></i>
      <span>Stats</span>
    </button>
    <a href="/fleet" class="flex flex-col items-center gap-1 text-slate-400 hover:text-indigo-400 text-xs transition">
      <i class="fa-solid fa-tower-broadcast text-base"></i>
      <span>Fleet Hub</span>
    </a>
    <button onclick="openSettingsModal()" class="flex flex-col items-center gap-1 text-slate-400 hover:text-white text-xs transition">
      <i class="fa-solid fa-sliders text-base"></i>
      <span>Settings</span>
    </button>
  </nav>

  <!-- Settings & Config Modal -->
  <div id="settingsModal" class="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm hidden flex items-center justify-center p-4">
    <div class="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-3xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden">
      <div class="p-6 border-b border-slate-800 flex items-center justify-between bg-slate-800/40">
        <div class="flex items-center gap-3">
          <div class="p-2 bg-indigo-600/20 text-indigo-400 rounded-lg">
            <i class="fa-solid fa-sliders"></i>
          </div>
          <h3 class="text-xl font-bold text-white">Bot & Hardware Configuration</h3>
        </div>
        <button onclick="closeSettingsModal()" class="text-slate-400 hover:text-white text-xl">
          <i class="fa-solid fa-xmark"></i>
        </button>
      </div>

      <!-- Settings Tabs -->
      <div class="flex border-b border-slate-800 bg-slate-950/40 px-6 gap-6 text-sm font-medium overflow-x-auto">
        <button onclick="switchSettingsTab('audio')" id="tabBtnAudio" class="py-3 text-indigo-400 border-b-2 border-indigo-500 whitespace-nowrap">🎤 Audio & Elevation</button>
        <button onclick="switchSettingsTab('wifi')" id="tabBtnWifi" class="py-3 text-slate-400 hover:text-slate-200 whitespace-nowrap">📶 Wi-Fi Network</button>
        <button onclick="switchSettingsTab('social')" id="tabBtnSocial" class="py-3 text-slate-400 hover:text-slate-200 whitespace-nowrap">📣 Social Alerts</button>
        <button onclick="switchSettingsTab('system')" id="tabBtnSystem" class="py-3 text-slate-400 hover:text-slate-200 whitespace-nowrap">⚙️ System & Logs</button>
      </div>

      <!-- Settings Content Body -->
      <div class="p-6 overflow-y-auto space-y-6 flex-1 text-sm text-slate-300">
        
        <!-- Auth Key Banner -->
        <div class="bg-slate-800/60 p-3 rounded-xl border border-slate-700 flex items-center justify-between gap-3">
          <span class="text-xs text-slate-400">Admin Passcode:</span>
          <input type="password" id="adminPasscode" placeholder="Enter admin passcode" class="bg-slate-950 border border-slate-700 rounded-lg px-3 py-1 text-xs text-white">
        </div>

        <!-- Tab 1: Audio & Triangulation -->
        <div id="tabAudio" class="space-y-4">
          <div class="p-4 bg-indigo-950/30 border border-indigo-500/30 rounded-xl space-y-4">
            <div class="flex items-center justify-between">
              <h4 class="font-bold text-indigo-300 flex items-center gap-2">
                <i class="fa-solid fa-triangle-circle-square"></i> Distance & Elevation Triangulation
              </h4>
              <span class="text-[11px] text-indigo-400 bg-indigo-900/50 px-2.5 py-0.5 rounded-full border border-indigo-500/30 font-semibold font-mono">Acoustic 3D Ray</span>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label class="block text-xs font-semibold text-slate-400 uppercase mb-1">Street / Road Name</label>
                <input type="text" id="cfgStreetName" placeholder="e.g. 98th Ave / Whyte Ave" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-white text-xs">
              </div>
              <div>
                <label class="block text-xs font-semibold text-slate-400 uppercase mb-1">Location Label</label>
                <input type="text" id="cfgLocationName" placeholder="e.g. 10th Floor Balcony" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-white text-xs">
              </div>
            </div>

            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 bg-slate-900/80 p-3.5 rounded-xl border border-slate-800">
              <div>
                <div class="flex justify-between items-center mb-1">
                  <label class="text-xs font-semibold text-slate-300">Floor Level</label>
                  <span id="floorLabelText" class="text-xs font-mono font-bold text-indigo-400">Floor 3 (~6m)</span>
                </div>
                <input type="range" id="cfgFloorNumber" min="1" max="30" step="1" value="3" oninput="calculateTriangulation()" class="w-full accent-indigo-500">
                <p class="text-[10px] text-slate-500 mt-1">1 = Ground level, 10 = ~27m elevation</p>
              </div>

              <div>
                <div class="flex justify-between items-center mb-1">
                  <label class="text-xs font-semibold text-slate-300">Horizontal Setback from Road</label>
                  <span id="setbackLabelText" class="text-xs font-mono font-bold text-indigo-400">5.0 m</span>
                </div>
                <input type="range" id="cfgSetbackMeters" min="1" max="60" step="0.5" value="5" oninput="calculateTriangulation()" class="w-full accent-indigo-500">
                <p class="text-[10px] text-slate-500 mt-1">Distance from building edge to road lane</p>
              </div>
            </div>

            <div class="p-3 bg-indigo-900/30 border border-indigo-500/30 rounded-xl space-y-1 font-mono text-xs">
              <div class="flex items-center justify-between text-indigo-200">
                <span>📐 Triangulated Line-of-Sight Distance:</span>
                <span id="triangulatedDistText" class="font-bold text-emerald-400 text-sm">-- m</span>
              </div>
              <div class="flex items-center justify-between text-indigo-300/90 text-[11px]">
                <span>Acoustic Attenuation from Tailpipe:</span>
                <span id="triangulatedLossText" class="font-bold text-amber-300">-- dB</span>
              </div>
              <p id="triangulatedFormulaText" class="text-[10px] text-slate-400 pt-1 border-t border-indigo-500/20"></p>
            </div>
          </div>

          <div>
            <label class="block text-xs font-semibold text-slate-400 uppercase mb-2">Microphone Device</label>
            <select id="cfgAudioDevice" class="w-full bg-slate-800 border border-slate-700 rounded-xl p-3 text-white"></select>
          </div>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label class="block text-xs font-semibold text-slate-400 uppercase mb-1">Trigger Threshold (dBA)</label>
              <input type="number" id="cfgThreshold" step="0.5" class="w-full bg-slate-800 border border-slate-700 rounded-xl p-3 text-white">
            </div>
            <div>
              <label class="block text-xs font-semibold text-slate-400 uppercase mb-1">Calibration Offset (dB)</label>
              <input type="number" id="cfgOffset" step="0.5" class="w-full bg-slate-800 border border-slate-700 rounded-xl p-3 text-white">
            </div>
          </div>
        </div>

        <!-- Tab 2: Wi-Fi Network -->
        <div id="tabWifi" class="space-y-4 hidden">
          <div class="p-4 bg-emerald-950/30 border border-emerald-500/30 rounded-xl space-y-4">
            <div class="flex items-center justify-between">
              <h4 class="font-bold text-emerald-300 flex items-center gap-2">
                <i class="fa-solid fa-wifi"></i> Wi-Fi Network Setup
              </h4>
              <button onclick="scanWifi()" class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-semibold border border-slate-700 transition">
                <i class="fa-solid fa-satellite-dish"></i> Scan Networks
              </button>
            </div>
            <div id="wifiList" class="space-y-2">
              <p class="text-xs text-slate-500">Click "Scan Networks" to search for nearby Wi-Fi routers.</p>
            </div>
            <div class="p-3.5 bg-slate-900/90 rounded-xl border border-slate-800 space-y-3">
              <input type="text" id="wifiSsidInput" placeholder="Select above or type Wi-Fi SSID" class="w-full bg-slate-950 border border-slate-700 rounded-lg p-2.5 text-white text-xs">
              <input type="password" id="wifiPasswordInput" placeholder="Enter Wi-Fi password" class="w-full bg-slate-950 border border-slate-700 rounded-lg p-2.5 text-white text-xs">
              <button onclick="connectWifi()" class="w-full py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-lg text-xs">
                Join Wi-Fi Network
              </button>
            </div>
          </div>
        </div>

        <!-- Tab 3: Social Alerts -->
        <div id="tabSocial" class="space-y-6 hidden">
          <div class="p-4 bg-slate-800/40 rounded-xl border border-slate-700/60 space-y-3">
            <div class="flex items-center justify-between">
              <h4 class="font-bold text-sky-400 flex items-center gap-2"><i class="fa-solid fa-cloud"></i> Bluesky</h4>
              <input type="checkbox" id="cfgBlueskyEnabled" class="w-5 h-5 rounded accent-sky-500">
            </div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
              <input type="text" id="cfgBlueskyHandle" placeholder="Handle (e.g. mynoisebot.bsky.social)" class="bg-slate-900 border border-slate-700 rounded-lg p-2 text-white">
              <input type="password" id="cfgBlueskyPassword" placeholder="App Password" class="bg-slate-900 border border-slate-700 rounded-lg p-2 text-white">
            </div>
          </div>
        </div>

        <!-- Tab 4: System & Logs -->
        <div id="tabSystem" class="space-y-4 hidden">
          <div class="flex items-center justify-between">
            <h4 class="font-bold text-white">Live System Logs</h4>
            <button onclick="fetchLogs()" class="px-3 py-1 bg-slate-800 text-xs rounded-lg hover:bg-slate-700">Refresh Logs</button>
          </div>
          <pre id="systemLogs" class="bg-black/80 border border-slate-800 p-3 rounded-xl text-xs font-mono text-emerald-400 h-48 overflow-y-auto whitespace-pre-wrap">Loading logs...</pre>
        </div>

      </div>

      <!-- Modal Footer -->
      <div class="p-4 border-t border-slate-800 bg-slate-950/60 flex items-center justify-end gap-3">
        <button onclick="closeSettingsModal()" class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl">Cancel</button>
        <button onclick="saveSettings()" class="px-5 py-2 bg-indigo-600 hover:bg-indigo-500 text-white font-semibold rounded-xl shadow-lg shadow-indigo-600/30">Save & Apply</button>
      </div>
    </div>
  </div>

  <script>
    let allEvents = [];
    let loadedConfig = {};
    let chartInstance = null;

    function switchMainTab(tab) {
      if (tab === 'live') {
        document.getElementById('viewLive').classList.remove('hidden');
        document.getElementById('viewStats').classList.add('hidden');
        document.getElementById('navBtnLive').className = 'flex flex-col items-center gap-1 text-indigo-400 font-semibold text-xs';
        document.getElementById('navBtnStats').className = 'flex flex-col items-center gap-1 text-slate-400 hover:text-white text-xs';
      } else if (tab === 'stats') {
        document.getElementById('viewLive').classList.add('hidden');
        document.getElementById('viewStats').classList.remove('hidden');
        document.getElementById('navBtnStats').className = 'flex flex-col items-center gap-1 text-indigo-400 font-semibold text-xs';
        document.getElementById('navBtnLive').className = 'flex flex-col items-center gap-1 text-slate-400 hover:text-white text-xs';
        renderDailyChart();
      }
    }

    function calculateTriangulation() {
      const floor = parseInt(document.getElementById('cfgFloorNumber').value) || 1;
      const setback = parseFloat(document.getElementById('cfgSetbackMeters').value) || 5.0;
      
      const height = (floor - 1) * 3.0;
      const dist = Math.sqrt(Math.pow(setback, 2) + Math.pow(height, 2));
      const finalDist = Math.max(0.5, dist);

      document.getElementById('floorLabelText').innerText = 'Floor ' + floor + ' (~' + height.toFixed(0) + 'm height)';
      document.getElementById('setbackLabelText').innerText = setback.toFixed(1) + ' m';
      document.getElementById('triangulatedDistText').innerText = finalDist.toFixed(1) + ' meters';

      const loss = 20 * Math.log10(finalDist / 0.5);
      document.getElementById('triangulatedLossText').innerText = '+' + loss.toFixed(1) + ' dB';

      document.getElementById('triangulatedFormulaText').innerText = 
        'Formula: √(' + setback.toFixed(1) + 'm setback² + ' + height.toFixed(0) + 'm height²) = ' + finalDist.toFixed(1) + 'm line-of-sight. A 75 dBA sound at your mic = ~' + (75 + loss).toFixed(1) + ' dBA at tailpipe.';

      return finalDist;
    }

    async function fetchEvents() {
      try {
        const res = await fetch('/api/events');
        allEvents = await res.json();
        renderEvents();
        if (!document.getElementById('viewStats').classList.contains('hidden')) {
          renderDailyChart();
        }
      } catch (e) {
        console.error(e);
      }
    }

    function renderDailyChart() {
      const ctx = document.getElementById('dailyEventsChart');
      if (!ctx) return;

      const countsByDay = {};
      const today = new Date();
      for (let i = 13; i >= 0; i--) {
        const d = new Date(today);
        d.setDate(d.getDate() - i);
        const key = d.toISOString().split('T')[0];
        countsByDay[key] = 0;
      }

      allEvents.forEach(ev => {
        if (ev.date && countsByDay[ev.date] !== undefined) {
          countsByDay[ev.date]++;
        }
      });

      const labels = Object.keys(countsByDay).map(k => k.slice(5));
      const data = Object.values(countsByDay);

      if (chartInstance) {
        chartInstance.destroy();
      }

      chartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: labels,
          datasets: [{
            label: 'Noise Events',
            data: data,
            backgroundColor: 'rgba(99, 102, 241, 0.7)',
            borderColor: 'rgba(99, 102, 241, 1)',
            borderWidth: 1.5,
            borderRadius: 6
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            y: { beginAtZero: true, ticks: { stepSize: 1, color: '#94a3b8' }, grid: { color: 'rgba(255, 255, 255, 0.05)' } },
            x: { ticks: { color: '#94a3b8' }, grid: { display: false } }
          }
        }
      });
    }

    function renderEvents() {
      const filter = document.getElementById('filterTag').value;
      const tbody = document.getElementById('eventsTableBody');
      const filtered = filter === 'all' ? allEvents : allEvents.filter(e => e.tag === filter);

      let vehicleCount = allEvents.filter(e => e.tag === 'traffic' || e.tag === 'vehicle').length;
      let bylawCount = allEvents.filter(e => e.dba >= 70).length;
      let peakDba = allEvents.length > 0 ? Math.max(...allEvents.map(e => e.dba)) : 0;

      document.getElementById('statTotal').innerText = allEvents.length;
      document.getElementById('statVehicle').innerText = vehicleCount;
      document.getElementById('statBylaw').innerText = bylawCount;
      document.getElementById('statPeak').innerText = peakDba > 0 ? peakDba + ' dBA' : '-- dBA';

      if (filtered.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="py-8 text-center text-slate-500">No events found matching criteria.</td></tr>';
        return;
      }

      tbody.innerHTML = filtered.map(ev => {
        const isTraffic = ev.tag === 'traffic' || ev.tag === 'vehicle';
        const isSiren = ev.tag === 'siren';
        const isConst = ev.tag === 'construction';
        const isWeather = ev.tag === 'weather';
        const isMisc = ev.tag === 'misc';
        const isReview = ev.tag === 'review';

        return `
          <tr class="hover:bg-slate-800/40 transition">
            <td class="py-3 px-6 font-mono text-slate-300">${ev.datetime.replace('T', ' ')}</td>
            <td class="py-3 px-6 font-bold ${ev.dba >= 80 ? 'text-rose-400' : ev.dba >= 70 ? 'text-amber-400' : 'text-slate-200'}">${ev.dba} dBA</td>
            <td class="py-3 px-6">
              <select onchange="reclassifyEvent('${ev.filename}', this.value)" class="bg-slate-800/90 border border-slate-700 text-xs font-semibold text-slate-200 rounded-lg px-2 py-1 cursor-pointer focus:ring-1 focus:ring-indigo-500">
                <option value="traffic" ${isTraffic ? 'selected' : ''}>🚗 Traffic</option>
                <option value="siren" ${isSiren ? 'selected' : ''}>🚨 Siren</option>
                <option value="construction" ${isConst ? 'selected' : ''}>🏗️ Construction</option>
                <option value="weather" ${isWeather ? 'selected' : ''}>🌧️ Weather</option>
                <option value="misc" ${isMisc ? 'selected' : ''}>❓ Misc</option>
                <option value="review" ${isReview ? 'selected' : ''}>⚠️ Review</option>
              </select>
            </td>
            <td class="py-3 px-6">
              <audio controls preload="none" class="h-8 max-w-[200px]" src="${ev.url}"></audio>
            </td>
            <td class="py-3 px-6 text-right">
              <button onclick="deleteEvent('${ev.filename}')" class="text-slate-500 hover:text-rose-400 p-1.5 transition"><i class="fa-solid fa-trash"></i></button>
            </td>
          </tr>
        `;
      }).join('');
    }

    async function reclassifyEvent(filename, newTag) {
      try {
        const res = await fetch('/api/reclassify/' + encodeURIComponent(filename), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tag: newTag })
        });
        if (res.ok) fetchEvents();
        else alert('Failed to reclassify event');
      } catch (e) {
        alert(e);
      }
    }

    async function deleteEvent(filename) {
      const code = document.getElementById('adminPasscode').value || prompt('Enter admin passcode:');
      if (!code) return;
      if (!confirm('Delete this event recording?')) return;
      try {
        const res = await fetch('/api/delete/' + filename + '?key=' + encodeURIComponent(code), { method: 'POST' });
        if (res.ok) fetchEvents();
        else alert('Failed or Unauthorized');
      } catch (e) {
        alert(e);
      }
    }

    setInterval(async () => {
      try {
        const res = await fetch('/api/live-level');
        const data = await res.json();
        const dba = data.current_dba || 0;
        document.getElementById('liveDbaText').innerText = dba.toFixed(1);
        
        const dist = loadedConfig.distance_to_road_meters || 10.0;
        const loss = 20 * Math.log10(Math.max(0.5, dist) / 0.5);
        document.getElementById('liveTailpipeText').innerText = 'Est. Tailpipe: ' + (dba + loss).toFixed(1) + ' dBA';

        const percent = Math.min(100, Math.max(0, ((dba - 30) / (105 - 30)) * 100));
        document.getElementById('liveMeterFill').style.width = percent + '%';
      } catch (e) {}
    }, 400);

    function openSettingsModal() {
      document.getElementById('settingsModal').classList.remove('hidden');
      loadDevicesAndConfig();
    }

    function closeSettingsModal() {
      document.getElementById('settingsModal').classList.add('hidden');
    }

    function switchSettingsTab(tab) {
      ['audio', 'wifi', 'social', 'system'].forEach(t => {
        const el = document.getElementById('tab' + t.charAt(0).toUpperCase() + t.slice(1));
        const btn = document.getElementById('tabBtn' + t.charAt(0).toUpperCase() + t.slice(1));
        if (el) el.classList.add('hidden');
        if (btn) btn.className = 'py-3 text-slate-400 hover:text-slate-200 whitespace-nowrap';
      });
      const activeEl = document.getElementById('tab' + tab.charAt(0).toUpperCase() + tab.slice(1));
      const activeBtn = document.getElementById('tabBtn' + tab.charAt(0).toUpperCase() + tab.slice(1));
      if (activeEl) activeEl.classList.remove('hidden');
      if (activeBtn) activeBtn.className = 'py-3 text-indigo-400 border-b-2 border-indigo-500 font-semibold whitespace-nowrap';
      if (tab === 'system') fetchLogs();
      if (tab === 'wifi') scanWifi();
    }

    async function loadDevicesAndConfig() {
      const code = document.getElementById('adminPasscode').value || 'admin123';
      try {
        const [devRes, cfgRes] = await Promise.all([
          fetch('/api/audio-devices'),
          fetch('/api/config?key=' + encodeURIComponent(code))
        ]);
        const devs = await devRes.json();
        const devSelect = document.getElementById('cfgAudioDevice');
        devSelect.innerHTML = devs.map(d => `<option value="${d.index}">[#${d.index}] ${d.name} (${d.channels} ch)</option>`).join('');

        if (cfgRes.ok) {
          loadedConfig = await cfgRes.json();
          document.getElementById('cfgStreetName').value = loadedConfig.street_name || '98th Ave';
          document.getElementById('cfgLocationName').value = loadedConfig.location_name || 'Balcony';
          document.getElementById('cfgFloorNumber').value = loadedConfig.floor_number || 3;
          document.getElementById('cfgSetbackMeters').value = loadedConfig.horizontal_setback_meters || 5.0;
          calculateTriangulation();
          document.getElementById('headerSubtitle').innerText = (loadedConfig.street_name || 'Road') + ' • ' + (loadedConfig.location_name || 'Sensor');
          document.getElementById('cfgThreshold').value = loadedConfig.threshold_dba || 75;
          document.getElementById('cfgOffset').value = loadedConfig.calibration_offset || 50;

          if (loadedConfig.audio_device_index !== null && loadedConfig.audio_device_index !== undefined) {
            devSelect.value = loadedConfig.audio_device_index;
          }

          document.getElementById('cfgBlueskyEnabled').checked = loadedConfig.bluesky?.enabled || false;
          document.getElementById('cfgBlueskyHandle').value = loadedConfig.bluesky?.handle || '';
          document.getElementById('cfgBlueskyPassword').value = loadedConfig.bluesky?.app_password || '';
        }
      } catch (e) {
        console.error(e);
      }
    }

    async function saveSettings() {
      const code = document.getElementById('adminPasscode').value || 'admin123';
      const devVal = document.getElementById('cfgAudioDevice').value;
      const finalDist = calculateTriangulation();

      const payload = {
        ...loadedConfig,
        admin_passcode: code,
        street_name: document.getElementById('cfgStreetName').value,
        location_name: document.getElementById('cfgLocationName').value,
        floor_number: parseInt(document.getElementById('cfgFloorNumber').value),
        horizontal_setback_meters: parseFloat(document.getElementById('cfgSetbackMeters').value),
        distance_to_road_meters: finalDist,
        audio_device_index: devVal !== "" ? parseInt(devVal) : null,
        threshold_dba: parseFloat(document.getElementById('cfgThreshold').value),
        calibration_offset: parseFloat(document.getElementById('cfgOffset').value),
        bluesky: {
          ...loadedConfig.bluesky,
          enabled: document.getElementById('cfgBlueskyEnabled').checked,
          handle: document.getElementById('cfgBlueskyHandle').value,
          app_password: document.getElementById('cfgBlueskyPassword').value
        }
      };

      try {
        const res = await fetch('/api/config?key=' + encodeURIComponent(code), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        if (res.ok) {
          alert('Settings saved and audio detector reloaded!');
          closeSettingsModal();
          loadDevicesAndConfig();
        } else {
          alert('Error saving settings.');
        }
      } catch (e) {
        alert(e);
      }
    }

    async function scanWifi() {
      const code = document.getElementById('adminPasscode').value || 'admin123';
      const listEl = document.getElementById('wifiList');
      listEl.innerHTML = '<p class="text-xs text-indigo-400 py-2"><i class="fa-solid fa-spinner fa-spin"></i> Scanning for nearby Wi-Fi networks...</p>';
      try {
        const res = await fetch('/api/wifi/scan?key=' + encodeURIComponent(code));
        const nets = await res.json();
        if (!nets || nets.length === 0) {
          listEl.innerHTML = '<p class="text-xs text-slate-400 py-1">No scanned networks returned. Type your Wi-Fi name in the box below to connect.</p>';
          return;
        }
        listEl.innerHTML = nets.map(n => `
          <div onclick="document.getElementById('wifiSsidInput').value = '${n.ssid}'" class="p-2.5 bg-slate-900 hover:bg-slate-800 border border-slate-800 rounded-lg flex items-center justify-between cursor-pointer">
            <span class="font-medium text-white text-xs">${n.ssid}</span>
            <span class="text-slate-400 text-xs">${n.signal}%</span>
          </div>
        `).join('');
      } catch (e) {
        listEl.innerHTML = '<p class="text-xs text-slate-400 py-1">Type your Wi-Fi SSID and password in the boxes below.</p>';
      }
    }

    async function connectWifi() {
      const code = document.getElementById('adminPasscode').value || 'admin123';
      const ssid = document.getElementById('wifiSsidInput').value;
      const password = document.getElementById('wifiPasswordInput').value;
      if (!ssid) return alert('Select or type a Wi-Fi name');
      try {
        const res = await fetch('/api/wifi/connect?key=' + encodeURIComponent(code), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ssid, password })
        });
        const d = await res.json();
        alert(d.message || d.error);
      } catch (e) {
        alert(e);
      }
    }

    async function fetchLogs() {
      const code = document.getElementById('adminPasscode').value || 'admin123';
      try {
        const res = await fetch('/api/logs?key=' + encodeURIComponent(code));
        const d = await res.json();
        document.getElementById('systemLogs').innerText = d.logs || 'No log messages yet.';
      } catch (e) {
        document.getElementById('systemLogs').innerText = 'Error: ' + e;
      }
    }

    fetchEvents();
  </script>
</body>
</html>
"""

HTML_FLEET = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Edmonton Noise Watch — Citywide Fleet Hub</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    body { background-color: #0b1120; color: #f8fafc; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    .glass-panel { background: rgba(15, 23, 42, 0.75); backdrop-filter: blur(16px); border: 1px solid rgba(255, 255, 255, 0.07); }
    .status-pulse-green { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); animation: pulseGreen 2s infinite; }
    .status-pulse-red { box-shadow: 0 0 0 0 rgba(244, 63, 94, 0.7); animation: pulseRed 2s infinite; }
    @keyframes pulseGreen {
      0% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
      70% { box-shadow: 0 0 0 8px rgba(16, 185, 129, 0); }
      100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
    }
    @keyframes pulseRed {
      0% { box-shadow: 0 0 0 0 rgba(244, 63, 94, 0.7); }
      70% { box-shadow: 0 0 0 8px rgba(244, 63, 94, 0); }
      100% { box-shadow: 0 0 0 0 rgba(244, 63, 94, 0); }
    }
  </style>
</head>
<body class="min-h-screen p-4 lg:p-6 space-y-6">

  <!-- Top App Bar -->
  <header class="glass-panel p-5 rounded-2xl flex flex-col md:flex-row md:items-center justify-between gap-4 shadow-2xl border-indigo-500/20">
    <div class="flex items-center gap-4">
      <div class="w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-white text-2xl shadow-lg shadow-indigo-500/30">
        <i class="fa-solid fa-tower-broadcast"></i>
      </div>
      <div>
        <div class="flex items-center gap-2.5">
          <h1 class="text-xl font-black text-white tracking-tight">Edmonton Noise Watch <span class="text-indigo-400 font-medium text-sm">| Citywide Fleet Hub</span></h1>
          <span class="px-2.5 py-0.5 bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 rounded-full text-xs font-bold font-mono flex items-center gap-1.5">
            <span class="w-2 h-2 rounded-full bg-emerald-400 status-pulse-green"></span> 24/7 Pi Hub Active
          </span>
        </div>
        <p class="text-xs text-slate-400 mt-0.5">Monitoring all connected community stations across Edmonton</p>
      </div>
    </div>

    <!-- Actions -->
    <div class="flex items-center gap-3">
      <a href="/" class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-xl text-xs font-bold flex items-center gap-1.5 border border-slate-700 transition">
        <i class="fa-solid fa-house"></i> My Balcony Bot
      </a>
      <div class="bg-slate-900/80 border border-slate-800 rounded-xl px-4 py-2 text-right">
        <span class="text-[10px] uppercase tracking-wider text-slate-400 font-bold block">Active Stations</span>
        <span id="headerOnlineCount" class="text-lg font-black text-emerald-400 font-mono">1 Active</span>
      </div>
    </div>
  </header>

  <!-- Connected Raspberry Pi Stations Grid -->
  <div>
    <div class="flex items-center justify-between mb-3 px-1">
      <h2 class="text-sm font-bold text-slate-300 uppercase tracking-wider flex items-center gap-2">
        <i class="fa-solid fa-microchip text-indigo-400"></i> Connected Community Stations
      </h2>
      <span class="text-xs text-slate-400 font-mono">Auto-syncing every 4s</span>
    </div>

    <div id="stationsGrid" class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4"></div>
  </div>

  <!-- Multi-Station Analytics & Live Unified Stream -->
  <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
    <!-- Chart: Citywide Decibels -->
    <div class="glass-panel p-6 rounded-2xl shadow-xl lg:col-span-2 space-y-4">
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <div class="flex items-center gap-2.5">
          <i class="fa-solid fa-chart-line text-indigo-400"></i>
          <h3 class="text-base font-bold text-white">Live Citywide Noise Level Comparison</h3>
        </div>
        <span class="text-xs text-slate-400 font-mono">Real-time Telemetry</span>
      </div>
      <div class="h-64 w-full">
        <canvas id="citywideChart"></canvas>
      </div>
    </div>

    <!-- Live Unified Violation Stream -->
    <div class="glass-panel p-6 rounded-2xl shadow-xl space-y-4 flex flex-col">
      <div class="flex items-center justify-between border-b border-slate-800 pb-3">
        <h3 class="text-base font-bold text-white flex items-center gap-2">
          <i class="fa-solid fa-bullhorn text-rose-400"></i> Unified Violations
        </h3>
        <span class="text-[10px] px-2 py-0.5 bg-indigo-500/20 text-indigo-300 rounded font-mono">Citywide Feed</span>
      </div>

      <div id="unifiedFeed" class="space-y-3 overflow-y-auto max-h-64 flex-1 pr-1">
        <p class="text-xs text-slate-500 text-center py-8">Waiting for violations...</p>
      </div>
    </div>
  </div>

  <script>
    let chartInstance = null;

    async function fetchFleetData() {
      try {
        const res = await fetch('/api/fleet-data');
        const data = await res.json();
        renderStations(data.stations || []);
        renderFeed(data.recent_violations || []);
        renderChart(data.stations || []);
      } catch (e) {
        console.error(e);
      }
    }

    function renderStations(stations) {
      const grid = document.getElementById('stationsGrid');
      const onlineCount = stations.filter(s => s.is_online).length;
      document.getElementById('headerOnlineCount').innerText = `${onlineCount} / ${stations.length} Active`;

      grid.innerHTML = stations.map(s => {
        const isOnline = s.is_online;
        const loss = 20 * Math.log10(Math.max(0.5, s.distance_to_road_meters || 10) / 0.5);
        const estTailpipe = (s.current_dba + loss).toFixed(1);

        return `
          <div class="glass-panel p-5 rounded-2xl border-l-4 ${isOnline ? 'border-l-emerald-500' : 'border-l-rose-500 opacity-75'} space-y-4">
            <div class="flex items-start justify-between">
              <div>
                <div class="flex items-center gap-2">
                  <span class="w-2.5 h-2.5 rounded-full ${isOnline ? 'bg-emerald-500 status-pulse-green' : 'bg-rose-500 status-pulse-red'}"></span>
                  <h3 class="font-bold text-white text-base">${s.station_name}</h3>
                </div>
                <p class="text-xs text-slate-400 font-mono">${s.street_name} • Floor ${s.floor_number}</p>
              </div>
              <span class="px-2 py-0.5 ${isOnline ? 'bg-slate-800 text-slate-300' : 'bg-rose-950/60 text-rose-400'} border border-slate-700 text-[10px] font-mono rounded font-bold">
                ${isOnline ? s.version || 'v1.2.0' : 'OFFLINE'}
              </span>
            </div>

            <div class="bg-slate-900/90 rounded-xl p-3 border border-slate-800/80 flex items-center justify-between">
              <div>
                <span class="text-[10px] text-slate-400 block font-semibold">${isOnline ? 'LIVE SOUND LEVEL' : 'STATUS'}</span>
                <div class="flex items-baseline gap-1">
                  <span class="text-2xl font-black ${isOnline ? 'text-emerald-400' : 'text-slate-500'} font-mono">${isOnline ? s.current_dba.toFixed(1) : '--'}</span>
                  <span class="text-xs text-slate-400 font-bold">dBA</span>
                </div>
              </div>
              <div class="text-right">
                <span class="text-[10px] text-slate-400 block font-semibold">EST. TAILPIPE</span>
                <span class="text-sm font-bold ${isOnline ? 'text-amber-400' : 'text-rose-400'} font-mono">
                  ${isOnline ? `~${estTailpipe} dBA` : `${s.seconds_since_ping}s ago`}
                </span>
              </div>
            </div>

            <div class="flex items-center justify-between text-xs text-slate-400 pt-1 border-t border-slate-800">
              <span>Violations: <b class="text-white font-mono">${s.total_violations || 0}</b></span>
            </div>
          </div>
        `;
      }).join('');
    }

    function renderFeed(violations) {
      const feed = document.getElementById('unifiedFeed');
      if (violations.length === 0) {
        feed.innerHTML = '<p class="text-xs text-slate-500 text-center py-8">No violations recorded yet.</p>';
        return;
      }

      feed.innerHTML = violations.slice().reverse().map(v => `
        <div class="bg-slate-900/80 border border-slate-800 rounded-xl p-3 space-y-1.5">
          <div class="flex items-center justify-between">
            <span class="text-xs font-bold text-white flex items-center gap-1.5">
              <span class="w-2 h-2 rounded-full bg-indigo-400"></span> ${v.station_name} (${v.street_name})
            </span>
            <span class="text-[10px] text-slate-400 font-mono">${v.time_str}</span>
          </div>
          <div class="flex items-center justify-between text-xs">
            <span class="font-mono text-rose-400 font-bold">${v.dba} dBA (${v.tailpipe_dba || (v.dba + 25).toFixed(0)} dB Tailpipe)</span>
            <span class="px-2 py-0.5 bg-indigo-500/20 text-indigo-300 rounded text-[10px] font-semibold">${v.tag || 'traffic'}</span>
          </div>
        </div>
      `).join('');
    }

    function renderChart(stations) {
      const ctx = document.getElementById('citywideChart');
      if (!ctx) return;

      const colors = ['#10b981', '#6366f1', '#a855f7', '#f59e0b', '#ec4899'];
      const datasets = stations.map((s, idx) => {
        const hist = s.history || [];
        return {
          label: s.station_name,
          data: hist.map(h => h.dba),
          borderColor: colors[idx % colors.length],
          backgroundColor: 'transparent',
          tension: 0.3,
          borderWidth: 2
        };
      });

      const labels = (stations[0]?.history || []).map(h => h.time);

      if (chartInstance) chartInstance.destroy();

      chartInstance = new Chart(ctx, {
        type: 'line',
        data: {
          labels: labels.length > 0 ? labels : ['00:00', '00:05', '00:10', '00:15'],
          datasets: datasets.length > 0 ? datasets : [{ label: 'Waiting for data', data: [0,0,0,0], borderColor: '#64748b' }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { position: 'top', labels: { color: '#94a3b8', boxWidth: 10 } } },
          scales: {
            y: { title: { display: true, text: 'dBA', color: '#64748b' }, ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.05)' } },
            x: { ticks: { color: '#94a3b8' }, grid: { display: false } }
          }
        }
      });
    }

    fetchFleetData();
    setInterval(fetchFleetData, 4000);
  </script>
</body>
</html>
"""

def run_server(port=5000):
    server_address = ('', port)
    httpd = ThreadingHTTPServer(server_address, DashboardHandler)
    print(f"Noise Bot Web Dashboard active on http://0.0.0.0:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5000, help="Port to run dashboard on (default: 5000)")
    args = parser.parse_args()
    run_server(args.port)
