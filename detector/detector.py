import time
import threading

class AnomalyDetector:
    def __init__(self, monitor, baseline_calc, blocker, notifier, thresholds):
        self.monitor = monitor
        self.baseline_calc = baseline_calc
        self.blocker = blocker
        self.notifier = notifier
        
        # Load configurable thresholds
        self.z_limit = thresholds.get('z_score_limit', 3.0)
        self.rate_limit = thresholds.get('rate_multiplier_limit', 5.0)
        self.error_surge = thresholds.get('error_surge_multiplier', 3.0)
        
        self.running = False
        
    def start(self):
        """Starts the background loop that continuously checks for anomalies."""
        self.running = True
        self.thread = threading.Thread(target=self._detection_loop, daemon=True)
        self.thread.start()
        
    def _detection_loop(self):
        """Infinite loop checking for anomalies every 2 seconds."""
        while self.running:
            time.sleep(2)
            self.detect()
            
    def detect(self):
        """Fetches current live rates and baselines, and flags anomalies."""
        # 1. Fetch exactly how many requests occurred in the last 60 seconds
        global_rate, ip_rates, ip_errors = self.monitor.get_current_rates()
        
        # 2. Fetch the current established mean and stddev
        mean, stddev, baseline_error_rate = self.baseline_calc.get_baselines()
        
        # Do not detect anomalies if we haven't formed a baseline yet
        if mean == 0.0: 
            return
            
        # 3. Check for Global DDoS Attack (Spike across all IPs)
        # Convert absolute counts in 60s to requests per second
        global_rps = global_rate / 60.0
        self._check_anomaly("GLOBAL", global_rps, mean, stddev, 0, baseline_error_rate)
            
        # 4. Check for Per-IP Attacks
        for ip, rate in ip_rates.items():
            if self.blocker.is_banned(ip):
                continue # Skip processing for already banned IPs
                
            ip_rps = rate / 60.0
            ip_error_rps = ip_errors.get(ip, 0) / 60.0
            self._check_anomaly(ip, ip_rps, mean, stddev, ip_error_rps, baseline_error_rate)
            
    def _check_anomaly(self, entity, current_rate, mean, stddev, ip_error_rate, baseline_error_rate):
        """Evaluates math thresholds and triggers blocking/alerts if exceeded."""
        
        # Ignore trivial traffic (less than 1 request per second)
        if current_rate < 1.0:
            return
            
        # Add a floor to stddev to prevent infinity z-scores during perfectly flat traffic
        safe_stddev = max(stddev, 0.5)
        
        # Calculate standard Z-score
        z_score = (current_rate - mean) / safe_stddev
            
        # Error Surge Check: Tighten thresholds automatically
        active_z_limit = self.z_limit
        active_rate_limit = self.rate_limit
        
        if baseline_error_rate > 0 and ip_error_rate > (self.error_surge * baseline_error_rate):
            # If errors are surging (e.g. brute force), cut the tolerance in half
            active_z_limit = self.z_limit / 2
            active_rate_limit = self.rate_limit / 2
            
        is_anomalous = False
        condition_fired = ""
        
        # Trigger Condition 1: Z-score > limit
        if z_score > active_z_limit:
            is_anomalous = True
            condition_fired = f"Z-Score {z_score:.2f} > {active_z_limit:.2f}"
            
        # Trigger Condition 2: Rate is more than Xx the baseline mean
        safe_mean = max(mean, 1.0) # floor mean for multiplier logic
        if current_rate > (safe_mean * active_rate_limit):
            is_anomalous = True
            condition_fired = f"Rate {current_rate:.2f} > {active_rate_limit}x Mean ({mean:.2f})"
            
        # Trigger Actions
        if is_anomalous:
            if entity == "GLOBAL":
                # Rate limit global alerts to 1 per 60 seconds
                now = time.time()
                if not hasattr(self, 'last_global_alert'):
                    self.last_global_alert = 0
                if now - self.last_global_alert > 60:
                    self.notifier.send_alert(
                        ip="GLOBAL", 
                        condition=condition_fired, 
                        rate=current_rate, 
                        baseline=mean, 
                        duration=0
                    )
                    self.last_global_alert = now
            else:
                # Per-IP Anomaly -> Ban IP + Slack Alert
                duration = self.blocker.ban_ip(entity, condition_fired, current_rate, mean)
                self.notifier.send_alert(
                    ip=entity, 
                    condition=condition_fired, 
                    rate=current_rate, 
                    baseline=mean, 
                    duration=duration
                )
