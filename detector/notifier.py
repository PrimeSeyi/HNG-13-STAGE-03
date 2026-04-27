import requests
import time
import logging

class Notifier:
    def __init__(self, webhook_url):
        self.webhook_url = webhook_url
        
    def send_alert(self, ip, condition, rate, baseline, duration):
        """Sends an exact formatted payload to the provided Slack webhook."""
        if not self.webhook_url:
            return
            
        timestamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        duration_str = "Permanent" if duration == -1 else f"{duration}s"
        
        message = (
            f"🚨 *Security Alert*\n"
            f"• *Action/IP*: {ip}\n"
            f"• *Condition Fired*: {condition}\n"
            f"• *Current Rate*: {rate} req/s\n"
            f"• *Baseline*: {baseline:.2f} req/s\n"
            f"• *Ban Duration*: {duration_str}\n"
            f"• *Timestamp*: {timestamp}"
        )
        
        payload = {"text": message}
        try:
            # We timeout at 5 seconds so we don't accidentally block the thread
            r = requests.post(self.webhook_url, json=payload, timeout=5)
            logging.info(f'Slack alert sent for {ip}: status={r.status_code} response={r.text}')
        except Exception as e:
            logging.error(f'Slack alert FAILED for {ip}: {e}')
