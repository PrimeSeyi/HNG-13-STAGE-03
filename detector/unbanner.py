import time
import threading

class Unbanner:
    def __init__(self, backoff_schedule, notifier):
        self.backoff_schedule = backoff_schedule
        self.notifier = notifier
        
        # Track how many times an IP has been banned
        self.ip_offense_counts = {}
        
        # Track active unban schedules (IP -> Unix Timestamp to unban)
        self.scheduled_unbans = {} 
        self.running = False
        
    def start(self):
        """Starts the background loop to process scheduled unbans."""
        self.running = True
        self.thread = threading.Thread(target=self._unban_loop, daemon=True)
        self.thread.start()
        
    def get_ban_duration(self, ip):
        """Returns the appropriate ban duration from the backoff schedule."""
        offenses = self.ip_offense_counts.get(ip, 0)
        
        if offenses >= len(self.backoff_schedule):
            duration = self.backoff_schedule[-1] # -1 = Permanent
        else:
            duration = self.backoff_schedule[offenses]
            
        # Increment offense count for the next time they offend
        self.ip_offense_counts[ip] = offenses + 1
        return duration
        
    def schedule_unban(self, ip, duration_seconds, blocker_ref):
        """Registers a future timestamp when the IP should be unbanned."""
        self.blocker = blocker_ref # Store reference to blocker
        unban_time = time.time() + duration_seconds
        self.scheduled_unbans[ip] = unban_time
        
    def _unban_loop(self):
        """Constantly checks if any IP's ban duration has expired."""
        while self.running:
            time.sleep(5)
            now = time.time()
            
            # Find IPs whose scheduled unban time is in the past
            ips_to_unban = [ip for ip, unban_time in self.scheduled_unbans.items() if now >= unban_time]
            
            for ip in ips_to_unban:
                # Ask blocker to physically remove the iptables rule
                success = getattr(self, 'blocker').unban_ip_manually(ip)
                if success:
                    # Remove from our schedule
                    del self.scheduled_unbans[ip]
                    
                    # Criteria: "Send a Slack notification on every unban."
                    self.notifier.send_alert(
                        ip=ip,
                        condition="Auto-Unbanned",
                        rate=0,
                        baseline=0,
                        duration=0
                    )
