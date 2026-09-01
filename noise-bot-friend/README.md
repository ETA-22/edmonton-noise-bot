# 🔊 Edmonton Traffic Noise Monitor (Docker Edition)

An automated acoustic monitoring station designed for Raspberry Pi to detect, classify, log, and alert on excessive vehicle exhaust noise.

---

## ✨ Features
* **Containerized Deployment:** Powered by Docker Compose with `/dev/snd` pass-through and host networking.
* **Turnkey Web Settings (`/settings`):** Change USB microphone input devices, view live decibel calibration meters, configure Wi-Fi, and manage social alerts directly in the browser.
* **Acoustic A-Weighting (dBA):** Accurate digital bilinear A-weighting filter powered by SciPy.
* **Audio Classifier:** Spectral band analysis and crest-factor filtering to distinguish vehicle roar from rain, wind, and thunder.
* **Multi-Platform Alerts:** Optional push notifications to Bluesky, Twitter/X, Discord webhooks, and Email.
* **Audio Event Archiving:** Pre-trigger rolling buffer and post-trigger WAV recording with web playback.

---

## 🚀 Quick Start

```bash
# Clone or extract archive
cd noise-bot-friend

# Run automated installer
chmod +x install.sh
./install.sh
```

Open `http://localhost:5000` (or `http://<pi-ip>:5000`) in your browser to access the dashboard.
