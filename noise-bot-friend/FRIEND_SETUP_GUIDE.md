# 🔊 Traffic Noise Monitor - Quick Setup Guide

Welcome to the Traffic Noise Monitor! This guide walks you through getting your monitoring station running on your Raspberry Pi in under 5 minutes.

---

## 📦 What You Need
1. **Raspberry Pi** (Pi 3, Pi 4, Pi 5, or Pi Zero 2W) running Raspberry Pi OS.
2. **USB Microphone** (or USB sound card with 3.5mm mic).
3. **Ethernet Cable** (just for the initial 2-minute Wi-Fi setup).

---

## 🚀 Step 1: Initial Setup & 1-Step Install

1. **Plug in Hardware:**
   * Plug your **USB Microphone** into any USB port on the Pi.
   * Connect an **Ethernet cable** from your Wi-Fi router to the Pi.
   * Plug in the power supply.

2. **Copy the Bot to your Pi:**
   * Put `noise-bot-friend.zip` onto your Pi (via flash drive, scp, or download).
   * Unzip it and enter the folder:
     ```bash
     unzip noise-bot-friend.zip -d noise-bot-friend
     cd noise-bot-friend
     ```

3. **Run the Automated Installer:**
   ```bash
   chmod +x install.sh
   ./install.sh
   ```
   *(This automatically installs Docker, configures audio permissions, launches the bot, and starts **Watchtower** for automatic background updates).*

---

## 🌐 Step 2: Open the Web Dashboard

From any phone, laptop, or tablet on your home Wi-Fi, open your browser to:
```text
http://<your-pi-ip>:5000
```
*(The exact IP address is printed in green at the end of the installer).*

---

## ⚙️ Step 3: Configure in Your Browser (Phone or PC)

Tap the **Settings** button in the bottom navigation (Default passcode: `admin123`):

### 1. 🎤 Audio & Elevation Calibration
* **Floor Level Slider:** Select which floor you are on (e.g. Ground Floor, Floor 3, Floor 10).
* **Setback Slider:** Set how far your building is from the road (e.g. 5 meters).
  * *The app automatically triangulates the line-of-sight sound ray and calculates the exact acoustic loss to the vehicle tailpipe on the road below.*
* **Microphone:** Select your USB microphone from the dropdown.

### 2. 📶 Wi-Fi Network Setup (To Unplug Ethernet)
* Go to the **📶 Wi-Fi** tab and tap **Scan Networks**.
* Select your home Wi-Fi network, type your password, and click **Join Wi-Fi**.
* Once connected, you can **unplug the Ethernet cable** and move the Pi anywhere you like!

### 3. 📣 Bluesky Auto-Posting (Optional)
* Go to the **📣 Alerts** tab and toggle **Enable Bluesky**.
* **Generate an App Password:**
  1. On your Bluesky app/web, go to `Settings` $\rightarrow$ `Privacy and Security` $\rightarrow$ `App Passwords` $\rightarrow$ `Add App Password`.
  2. Name it *"Noise Bot"* and copy the password.
* Paste your Bluesky Handle (e.g. `yourname.bsky.social`) and the App Password.
* *(Optional)* Add target handles to tag (e.g. `@cityofedmonton.bsky.social`).
* Tap **Save & Apply**.

---

## 📊 Step 4: Monitoring, Stats & Re-Classifying

* **Live Tab:** View the real-time decibel meter and estimated tailpipe noise level.
* **Stats Tab:** View the **Daily Events Chart** (events per day over the past 14 days) and your total violation count.
* **Sound Clips & Re-Classification:** Listen to any 8-second recorded audio clip and change its tag on the fly using the dropdown (🚗 Traffic, 🚨 Siren, 🏗️ Construction, 🌧️ Weather, ❓ Misc).

---

## 🔄 Zero-Maintenance Auto Updates
Whenever new features or bug fixes are published, **Watchtower** automatically downloads the update and restarts the bot without touching your saved Wi-Fi, credentials, or audio recordings.
