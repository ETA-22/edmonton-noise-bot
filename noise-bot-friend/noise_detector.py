import os
import sys
import time
import json
import wave
import argparse
import logging
from collections import deque

import numpy as np
import pyaudio

try:
    import scipy.signal as signal
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

from notifier import Notifier
from audio_classifier import classify_audio

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "noise_bot.log")
LIVE_STATE_FILE = os.path.join(BASE_DIR, "live_audio_state.json")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
OUTPUT_DIR = os.path.join(BASE_DIR, "recordings")

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)

# Audio Constants
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 48000
CHUNK = 4096

def get_a_weighting_coefficients(fs):
    if not HAS_SCIPY:
        return None, None
    f1 = 20.598997
    f2 = 107.65265
    f3 = 737.86223
    f4 = 12194.217
    A1000 = 1.9997

    NUMs = [(2 * np.pi * f4)**2 * (10**(A1000 / 20)), 0, 0, 0, 0]
    p1 = [1, 4 * np.pi * f1, (2 * np.pi * f1)**2]
    p2 = [1, 4 * np.pi * f4, (2 * np.pi * f4)**2]
    p3 = [1, 2 * np.pi * f2]
    p4 = [1, 2 * np.pi * f3]
    
    den = np.polymul(p1, p2)
    den = np.polymul(den, p3)
    den = np.polymul(den, p4)

    b, a = signal.bilinear(NUMs, den, fs)
    return b, a

def get_audio_devices():
    p = pyaudio.PyAudio()
    devices = []
    try:
        info = p.get_host_api_info_by_index(0)
        numdevices = info.get('deviceCount', 0)
        for i in range(0, numdevices):
            try:
                device_info = p.get_device_info_by_host_api_device_index(0, i)
                if device_info.get('maxInputChannels', 0) > 0:
                    devices.append({
                        "index": i,
                        "name": device_info.get('name'),
                        "channels": device_info.get('maxInputChannels'),
                        "defaultSampleRate": device_info.get('defaultSampleRate')
                    })
            except Exception:
                pass
    finally:
        p.terminate()
    return devices

def main():
    parser = argparse.ArgumentParser(description="Noise Monitor Bot Engine")
    parser.add_argument("--list-devices", action="store_true", help="List audio input devices and exit")
    parser.add_argument("--device", type=int, default=None, help="Audio input device index")
    parser.add_argument("--test-mic", action="store_true", help="Live CLI meter mode")
    parser.add_argument("--threshold", type=float, default=None, help="Override noise threshold (dBA)")
    parser.add_argument("--offset", type=float, default=None, help="Override calibration offset (dB)")
    args = parser.parse_args()

    if args.list_devices:
        devs = get_audio_devices()
        print(json.dumps(devs, indent=2))
        return

    p = pyaudio.PyAudio()

    # Load configuration
    notifier = Notifier()
    config = notifier.config

    threshold_dba = args.threshold if args.threshold is not None else float(config.get("threshold_dba", 75.0))
    calibration_offset = args.offset if args.offset is not None else float(config.get("calibration_offset", 50.0))
    cooldown_period = float(config.get("cooldown_period_minutes", 2.0)) * 60.0
    save_audio = config.get("save_audio", True)
    output_dir = OUTPUT_DIR

    device_index = args.device if args.device is not None else config.get("audio_device_index", None)

    stream = None
    if device_index is not None:
        try:
            dev_info = p.get_device_info_by_host_api_device_index(0, device_index)
            logging.info(f"Attempting input device: {dev_info['name']} (Index {device_index})")
            stream = p.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=CHUNK
            )
        except Exception as e:
            logging.warning(f"Failed device index {device_index} ({e}), falling back to default device...")
            stream = None

    if stream is None:
        try:
            default_device = p.get_default_input_device_info()
            device_index = default_device['index']
            logging.info(f"Using default input device: {default_device['name']} (Index {device_index})")
            stream = p.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=CHUNK
            )
        except Exception as e:
            logging.error(f"No default input audio device found: {e}")
            p.terminate()
            sys.exit(1)

    b, a = get_a_weighting_coefficients(RATE)
    if HAS_SCIPY:
        logging.info("A-weighting filter enabled (dBA scale).")
    else:
        logging.warning("SciPy not installed. Running in raw dB mode.")

    chunks_per_sec = int(RATE / CHUNK)
    pre_trigger_seconds = 3
    post_trigger_seconds = int(config.get("record_event_seconds", 8))
    
    audio_history = deque(maxlen=int(pre_trigger_seconds * chunks_per_sec))
    post_trigger_chunks = int(post_trigger_seconds * chunks_per_sec)

    logging.info(f"Audio engine active (Mic Index: {device_index}). Writing telemetry to {LIVE_STATE_FILE}...")
    last_notification_time = 0
    is_recording_event = False
    event_start_time = 0
    event_peak_dba = 0.0
    post_trigger_count = 0
    event_frames = []

    filter_state = np.zeros(6) if HAS_SCIPY and b is not None else None
    last_state_write_time = 0

    try:
        while True:
            try:
                data = stream.read(CHUNK, exception_on_overflow=False)
            except IOError:
                continue

            audio_history.append(data)

            signal_data = np.frombuffer(data, dtype=np.int16).astype(np.float64)
            normalized = signal_data / 32768.0

            if HAS_SCIPY and b is not None and a is not None:
                weighted, filter_state = signal.lfilter(b, a, normalized, zi=filter_state)
            else:
                weighted = normalized

            rms = np.sqrt(np.mean(weighted ** 2))
            if rms > 1e-10:
                db_relative = 20 * np.log10(rms)
                dba = max(0.0, db_relative + calibration_offset)
            else:
                dba = 0.0

            # Write live state for web dashboard meter every 200ms
            now = time.time()
            if now - last_state_write_time > 0.2:
                last_state_write_time = now
                try:
                    state_payload = {
                        "timestamp": now,
                        "current_dba": round(dba, 1),
                        "is_recording": is_recording_event,
                        "threshold_dba": threshold_dba
                    }
                    with open(LIVE_STATE_FILE + ".tmp", "w") as f:
                        json.dump(state_payload, f)
                    os.replace(LIVE_STATE_FILE + ".tmp", LIVE_STATE_FILE)
                except Exception:
                    pass

            if args.test_mic:
                bar_length = int(dba / 2)
                bar = "=" * bar_length + " " * (50 - bar_length)
                sys.stdout.write(f"\rCurrent level: {dba:5.1f} dB(A) | [{bar}]")
                sys.stdout.flush()
                continue

            current_time = time.time()
            in_cooldown = (current_time - last_notification_time) < cooldown_period

            if not is_recording_event:
                if dba >= threshold_dba and not in_cooldown:
                    logging.info(f"Threshold exceeded! {dba:.1f} dBA >= {threshold_dba} dBA. Recording event...")
                    is_recording_event = True
                    event_start_time = current_time
                    event_peak_dba = dba
                    event_frames = list(audio_history)
                    post_trigger_count = 0
            else:
                event_frames.append(data)
                post_trigger_count += 1
                if dba > event_peak_dba:
                    event_peak_dba = dba

                if post_trigger_count >= post_trigger_chunks:
                    is_recording_event = False
                    last_notification_time = current_time
                    wav_path = None

                    if save_audio:
                        timestamp = time.strftime("%Y%m%d_%H%M%S")
                        temp_filename = f"noise_event_{timestamp}_{int(event_peak_dba)}dba_temp.wav"
                        temp_path = os.path.join(output_dir, temp_filename)

                        try:
                            os.makedirs(output_dir, exist_ok=True)
                            wf = wave.open(temp_path, 'wb')
                            wf.setnchannels(CHANNELS)
                            wf.setsampwidth(p.get_sample_size(FORMAT))
                            wf.setframerate(RATE)
                            wf.writeframes(b''.join(event_frames))
                            wf.close()

                            tag = classify_audio(temp_path)
                            final_filename = f"noise_event_{timestamp}_{int(event_peak_dba)}dba_{tag}.wav"
                            wav_path = os.path.join(output_dir, final_filename)
                            os.rename(temp_path, wav_path)
                            logging.info(f"Saved event recording ({tag}): {wav_path}")
                        except Exception as e:
                            logging.error(f"Failed to save WAV file: {e}")
                            wav_path = None

                    duration = post_trigger_seconds + pre_trigger_seconds
                    logging.info(f"Processing event: Peak {event_peak_dba:.1f} dBA, Duration {duration}s")
                    notifier.notify(event_peak_dba, wav_path=wav_path, duration_seconds=duration)

    except KeyboardInterrupt:
        logging.info("Stopping noise detector...")
    finally:
        if stream:
            stream.stop_stream()
            stream.close()
        p.terminate()

if __name__ == "__main__":
    main()
