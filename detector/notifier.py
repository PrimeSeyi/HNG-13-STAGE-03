import requests
import time

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
            requests.post(self.webhook_url, json=payload, timeout=5)
        except Exception:
            pass # Fail silently as this is an auxiliary feature
