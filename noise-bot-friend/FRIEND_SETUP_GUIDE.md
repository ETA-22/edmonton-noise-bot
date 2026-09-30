# 🔊 Edmonton Traffic Noise Monitor — Quick Setup Guide

Welcome to the Edmonton Traffic Noise Monitor! This guide walks you through getting your monitoring station running on your Raspberry Pi in under 3 minutes.

---

## 📦 What You Need
1. **Raspberry Pi** (Pi 3, Pi 4, Pi 5, or Pi Zero 2W) running Raspberry Pi OS.
2. **USB Microphone** (or USB sound card with 3.5mm mic).
3. **Power Adapter** (USB power supply for your Pi).
*(Note: An Ethernet cable is **100% optional** — the bot has a built-in IoT Wi-Fi Hotspot for easy phone setup!)*

---

## 🚀 Setup Option A: The IoT Hotspot Setup (Zero Cables / Phone Setup) — ⭐ RECOMMENDED

Just like setting up a smart plug, Sonos, or Chromecast:

1. **Plug in Hardware:**
   * Plug your **USB Microphone** into any USB port on the Pi.
   * Plug in the power supply. *(Leave Ethernet unplugged!)*

2. **Connect to Hotspot on Your Phone:**
   * Wait ~60 seconds for the Pi to boot.
   * On your phone or laptop, open Wi-Fi settings and connect to:
     📶 **`Edmonton-Noise-Bot-Setup`** (No password needed).

3. **Complete the 60-Second Setup Wizard:**
   * A setup window will **automatically pop up** on your phone screen (Captive Portal).
   * Tap your home Wi-Fi network from the list and enter your Wi-Fi password.
   * Adjust your **Floor Level** slider (e.g. Floor 3) and Station Name.
   * *(Optional)* Set a custom admin passcode and Bluesky credentials.
   * Tap **"Connect & Start Monitoring"**.

4. **Done!**
   * The Pi will connect to your home Wi-Fi, shut down the setup hotspot, and start 24/7 noise monitoring!
   * Access your dashboard anytime on your home network at:
     👉 **`http://noise-bot.local:5000`**

---

## 🔌 Setup Option B: Ethernet Cable Setup (Direct Network)

If you prefer plugging directly into your home router:

1. Connect an Ethernet cable from your router to the Pi and plug in power.
2. Open your browser from any phone or PC on your network to:
   👉 **`http://noise-bot.local:5000`** (or your Pi's IP address).
3. Tap **Settings** (default passcode: `1811`):
   * Go to **📶 Wi-Fi**, click **Scan Networks**, select your home Wi-Fi, and join.
   * Once joined, you can unplug the Ethernet cable!

---

## 🛠️ Step 2: Audio & Microphone Calibration

In your web dashboard (`http://noise-bot.local:5000`):
1. Tap **Settings** (default passcode: `1811` or your custom passcode).
2. Verify your **USB Microphone** is selected in the dropdown.
3. Make sound near the microphone to watch the live decibel meter respond.
4. Set your **Setback Distance** (distance from your balcony/window to the road below).
   * *The acoustic engine automatically calculates line-of-sight sound attenuation from the road.*

---

## 📊 Daily Monitoring & Sound Clips
* **Live Tab:** View real-time dBA decibel levels and estimated tailpipe noise.
* **Stats Tab:** View violation charts and historical decibel trends.
* **Recordings:** Listen to recorded 8-second audio clips of loud vehicle spikes and tag them (🚗 Traffic, 🚨 Siren, 🏗️ Construction, 🌧️ Weather, ❓ Misc).

---

## 🔄 Zero-Maintenance Auto-Updates
Whenever updates or improvements are released, **Watchtower** automatically pulls the latest build and restarts the bot in the background without affecting your saved Wi-Fi or settings.
