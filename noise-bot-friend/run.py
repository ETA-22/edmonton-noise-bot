import os
import sys
import time
import signal
import subprocess
import threading

TRIGGER_FILE = ".reload_trigger"

def run_dashboard():
    port = os.environ.get("DASHBOARD_PORT", "5000")
    cmd = [sys.executable, "dashboard.py", "--port", str(port)]
    subprocess.run(cmd)

def start_detector():
    return subprocess.Popen([sys.executable, "noise_detector.py"])

def main():
    print("=== Starting Noise Bot Master Supervisor ===")
    
    # Initialize trigger file timestamp
    if os.path.exists(TRIGGER_FILE):
        try:
            os.remove(TRIGGER_FILE)
        except Exception:
            pass

    last_trigger_time = 0

    # Start dashboard in separate thread
    dash_thread = threading.Thread(target=run_dashboard, daemon=True)
    dash_thread.start()

    # Start detector subprocess
    detector_proc = start_detector()

    def signal_handler(sig, frame):
        print("\nShutting down Noise Bot...")
        if detector_proc and detector_proc.poll() is None:
            detector_proc.terminate()
            try:
                detector_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                detector_proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("Noise Bot running. Watching for configuration changes...")

    try:
        while True:
            time.sleep(1.0)
            
            # Check if detector crashed unexpectedly
            if detector_proc.poll() is not None:
                print("Warning: Noise detector stopped. Restarting in 3 seconds...")
                time.sleep(3.0)
                detector_proc = start_detector()

            # Check if reload triggered via dashboard settings UI
            if os.path.exists(TRIGGER_FILE):
                try:
                    mtime = os.path.getmtime(TRIGGER_FILE)
                    if mtime > last_trigger_time:
                        last_trigger_time = mtime
                        print("Reload signal received! Restarting audio detector engine...")
                        if detector_proc.poll() is None:
                            detector_proc.terminate()
                            try:
                                detector_proc.wait(timeout=3)
                            except subprocess.TimeoutExpired:
                                detector_proc.kill()
                        time.sleep(0.5)
                        detector_proc = start_detector()
                except Exception as e:
                    print(f"Reload check error: {e}")

    except KeyboardInterrupt:
        signal_handler(None, None)

if __name__ == "__main__":
    main()
