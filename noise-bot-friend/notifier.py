import os
import json
import logging
import smtplib
import time
import random
import math
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("noise_bot.log"),
        logging.StreamHandler()
    ]
)

class Notifier:
    def __init__(self, config_path="config.json"):
        self.config_path = config_path
        self.config = self.load_config()

    def load_config(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            elif os.path.exists("config.example.json"):
                with open("config.example.json", "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logging.error(f"Failed to load config file {self.config_path}: {e}")
        return {}

    def reload(self):
        self.config = self.load_config()

    def get_estimated_tailpipe_db(self, dba_level):
        """
        Calculates estimated sound pressure level at the vehicle tailpipe (0.5m)
        based on inverse-square law: loss = 20 * log10(distance / 0.5m).
        """
        distance = float(self.config.get("distance_to_road_meters", 15.0))
        distance = max(0.5, distance)
        # 20 * log10(d / 0.5)
        attenuation = 20.0 * math.log10(distance / 0.5)
        return dba_level + attenuation

    def notify(self, dba_level, audio_file_path=None):
        self.reload()
        muffler_db = self.get_estimated_tailpipe_db(dba_level)
        message = f"Noise threshold exceeded! Sensor: {dba_level:.1f} dBA | Est. Tailpipe: {muffler_db:.1f} dBA."
        logging.info(message)

        audio_url = None
        bluesky_enabled = self.config.get("bluesky", {}).get("enabled", False)
        discord_enabled = self.config.get("discord", {}).get("enabled", False)

        if (bluesky_enabled or discord_enabled) and audio_file_path and os.path.exists(audio_file_path):
            logging.info("Uploading audio clip to Catbox...")
            audio_url = self.upload_to_catbox(audio_file_path)

        # 1. Email Notification
        email_config = self.config.get("email", {})
        if email_config.get("enabled", False):
            self.send_email(dba_level, audio_file_path)

        # 2. Twitter Notification
        twitter_config = self.config.get("twitter", {})
        if twitter_config.get("enabled", False):
            self.send_tweet(dba_level, audio_file_path)

        # 3. Bluesky Notification
        if bluesky_enabled:
            self.send_bluesky(dba_level, audio_url)

        # 4. Discord Notification
        if discord_enabled:
            self.send_discord(dba_level, audio_url)

    def send_email(self, dba_level, audio_file_path=None):
        email_config = self.config.get("email", {})
        sender_email = email_config.get("sender_email")
        sender_password = email_config.get("sender_password")
        recipient_emails = email_config.get("recipient_emails", [])
        smtp_server = email_config.get("smtp_server", "smtp.gmail.com")
        smtp_port = email_config.get("smtp_port", 587)
        prefix = email_config.get("subject_prefix", "[Noise Alert]")

        if not sender_email or not sender_password or not recipient_emails:
            logging.error("Email is enabled but credentials or recipients are missing.")
            return

        muffler_db = self.get_estimated_tailpipe_db(dba_level)
        loc = self.config.get("location_name", "balcony")
        street = self.config.get("street_name", "nearby road")

        subject = f"{prefix}: {dba_level:.1f} dBA detected ({street})"
        body = (
            f"Hello,\n\n"
            f"This is an automated report from the Traffic Noise Monitor.\n\n"
            f"A vehicle on {street} has registered a peak sound pressure level of {dba_level:.1f} dBA at {loc}.\n"
            f"Estimated sound pressure level at the tailpipe / street is approximately {muffler_db:.1f} dBA.\n\n"
            f"Attached is a brief recording of the peak event for verification.\n\n"
            f"Regards,\nNoise Monitor Bot"
        )

        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = ", ".join(recipient_emails)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        if audio_file_path and os.path.exists(audio_file_path):
            try:
                filename = os.path.basename(audio_file_path)
                with open(audio_file_path, "rb") as attachment:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(attachment.read())
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", f"attachment; filename={filename}")
                msg.attach(part)
                logging.info(f"Attached audio file {filename} to email.")
            except Exception as e:
                logging.error(f"Failed to attach audio file: {e}")

        try:
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, recipient_emails, msg.as_string())
            server.quit()
            logging.info(f"Email successfully sent to {recipient_emails}")
        except Exception as e:
            logging.error(f"Failed to send email: {e}")

    def send_tweet(self, dba_level, audio_file_path=None):
        twitter_config = self.config.get("twitter", {})
        consumer_key = twitter_config.get("consumer_key")
        consumer_secret = twitter_config.get("consumer_secret")
        access_token = twitter_config.get("access_token")
        access_token_secret = twitter_config.get("access_token_secret")
        target_handles = twitter_config.get("target_handles", [])

        try:
            import tweepy
        except ImportError:
            logging.error("Tweepy is not installed. Run 'pip install tweepy' to use Twitter.")
            return

        if any(v == "YOUR_KEY" or not v for v in [consumer_key, consumer_secret, access_token, access_token_secret]):
            logging.error("Twitter keys are missing in config.")
            return

        current_time = time.strftime("%I:%M %p")
        muffler_db = self.get_estimated_tailpipe_db(dba_level)
        street = self.config.get("street_name", "the street")
        loc = self.config.get("location_name", "balcony")

        handles_str = " ".join(target_handles) if target_handles else ""

        templates = [
            f"⚠️ Traffic Noise Alert: peak {dba_level:.1f} dBA at {loc} ({street}) at {current_time}. (Est. {muffler_db:.1f} dBA at tailpipe). {handles_str}",
            f"Excessive vehicle noise on {street}: {dba_level:.1f} dBA at {loc} = ~{muffler_db:.1f} dBA at tailpipe at {current_time}. {handles_str}",
            f"Noise threshold exceeded on {street}: peak {dba_level:.1f} dBA at {current_time} (~{muffler_db:.1f} dBA at street level). {handles_str}"
        ]
        tweet_text = random.choice(templates).strip()

        try:
            client = tweepy.Client(
                consumer_key=consumer_key,
                consumer_secret=consumer_secret,
                access_token=access_token,
                access_token_secret=access_token_secret
            )
            response = client.create_tweet(text=tweet_text)
            logging.info(f"Tweet successfully posted! ID: {response.data.get('id')}")
        except Exception as e:
            logging.error(f"Failed to send tweet: {e}")

    def upload_to_catbox(self, file_path):
        try:
            import requests
            url = "https://catbox.moe/user/api.php"
            data = {"reqtype": "fileupload", "userhash": ""}
            with open(file_path, "rb") as f:
                files = {"fileToUpload": f}
                response = requests.post(url, data=data, files=files, timeout=15)
                if response.status_code == 200:
                    return response.text.strip()
        except Exception as e:
            logging.error(f"Failed to upload audio to Catbox: {e}")
        return None

    def send_bluesky(self, dba_level, audio_url=None):
        bluesky_config = self.config.get("bluesky", {})
        handle = bluesky_config.get("handle")
        app_password = bluesky_config.get("app_password")
        target_handles = bluesky_config.get("target_handles", [])

        try:
            from atproto import Client
        except ImportError:
            logging.error("atproto is not installed. Run 'pip install atproto' to use Bluesky.")
            return

        if not handle or not app_password:
            logging.error("Bluesky credentials are not configured in config.json.")
            return

        current_time = time.strftime("%I:%M %p")
        muffler_db = self.get_estimated_tailpipe_db(dba_level)
        street = self.config.get("street_name", "the street")
        loc = self.config.get("location_name", "balcony")

        templates = [
            f"🚨 Loud vehicle on {street}: {dba_level:.1f} dB at {loc} ({muffler_db:.1f} dB at tailpipe) at {current_time}.",
            f"Excessive noise event on {street}: {dba_level:.1f} dB at {loc} ({muffler_db:.1f} dB at street level) at {current_time}.",
            f"Heads up: a vehicle on {street} hit {dba_level:.1f} dB ({muffler_db:.1f} dB tailpipe) at {current_time}."
        ]
        post_text = random.choice(templates)

        if audio_url:
            post_text += f"\nListen: {audio_url}"

        if target_handles:
            handles_str = " ".join(target_handles)
            post_text += f"\nCc: {handles_str}"

        try:
            client = Client()
            client.login(handle, app_password)
            client.send_post(text=post_text)
            logging.info("Bluesky post successfully sent!")
        except Exception as e:
            logging.error(f"Failed to send Bluesky post: {e}")

    def send_discord(self, dba_level, audio_url=None):
        discord_config = self.config.get("discord", {})
        webhook_url = discord_config.get("webhook_url")

        if not webhook_url:
            logging.error("Discord webhook is enabled but webhook_url is missing.")
            return

        try:
            import requests
            current_time = time.strftime("%I:%M %p")
            muffler_db = self.get_estimated_tailpipe_db(dba_level)
            street = self.config.get("street_name", "the street")
            loc = self.config.get("location_name", "Balcony")

            embed = {
                "title": "🚨 Excessive Traffic Noise Detected!",
                "color": 15158332,
                "fields": [
                    {"name": "Location", "value": f"{loc} ({street})", "inline": True},
                    {"name": "Sensor Reading", "value": f"{dba_level:.1f} dBA", "inline": True},
                    {"name": "Est. Tailpipe Level", "value": f"{muffler_db:.1f} dBA", "inline": True},
                    {"name": "Time", "value": current_time, "inline": True}
                ],
                "description": "The bot has recorded a noise event."
            }

            if audio_url:
                embed["description"] += f"\n\n**[🔊 Listen to Recording]({audio_url})**"

            payload = {"embeds": [embed]}
            response = requests.post(webhook_url, json=payload, timeout=10)
            if response.status_code == 204:
                logging.info("Discord notification successfully sent!")
            else:
                logging.error(f"Failed to send Discord message: {response.status_code} {response.text}")
        except Exception as e:
            logging.error(f"Failed to send Discord notification: {e}")
