#Tails Nginx access logs natively and maintains 60s sliding windows.
import json
import time
import subprocess
import threading
from collections import deque, defaultdict
import logging

class LogMonitor:
    def __init__(self, log_file, window_size=60):
        self.log_file = log_file
        self.window_size = window_size
        
        # Sliding windows for the last 60 seconds (deque-based as required)
        self.global_window = deque()
        self.ip_windows = defaultdict(deque)
        self.ip_error_windows = defaultdict(deque)
        
        # Per-second aggregated data for baseline calculation (timestamp -> total requests)
        self.per_second_counts = defaultdict(int)
        self.per_second_errors = defaultdict(int)
        
        self.lock = threading.Lock()
        self.running = False
        
    def start(self):
        """Starts the tailing and cleanup background threads."""
        self.running = True
        self.thread = threading.Thread(target=self._tail_log, daemon=True)
        self.thread.start()
        
        self.cleanup_thread = threading.Thread(target=self._cleanup_old_data, daemon=True)
        self.cleanup_thread.start()

    def _tail_log(self):
        """Continuously tail the Nginx JSON log using subprocess."""
        process = subprocess.Popen(
            ['tail', '-F', self.log_file],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        
        try:
            for line in iter(process.stdout.readline, ''):
                if not self.running:
                    break
                if line:
                    self._process_line(line.strip())
        finally:
            process.terminate()

    def _process_line(self, line):
        """Parses a JSON log line and adds it to the sliding windows."""
        try:
            data = json.loads(line)
            source_ip = data.get("source_ip", "0.0.0.0")
            status = str(data.get("status", "200"))
            
            now = time.time()
            current_sec = int(now)
            
            is_error = status.startswith('4') or status.startswith('5')
            
            with self.lock:
                # Add to deques
                self.global_window.append(now)
                self.ip_windows[source_ip].append(now)
                
                # Add to per-second counter for baselines
                self.per_second_counts[current_sec] += 1
                
                if is_error:
                    self.ip_error_windows[source_ip].append(now)
                    self.per_second_errors[current_sec] += 1
                    
        except json.JSONDecodeError:
            pass # Ignore invalid JSON lines

    def _cleanup_old_data(self):
        """Runs in background to free memory by popping timestamps > 60s old."""
        while self.running:
            time.sleep(5)
            now = time.time()
            cutoff = now - self.window_size
            
            with self.lock:
                # Cleanup global window
                while self.global_window and self.global_window[0] < cutoff:
                    self.global_window.popleft()
                    
                # Cleanup IP windows
                empty_ips = []
                for ip, window in self.ip_windows.items():
                    while window and window[0] < cutoff:
                        window.popleft()
                    if not window:
                        empty_ips.append(ip)
                        
                for ip in empty_ips:
                    del self.ip_windows[ip]
                    
                # Cleanup IP error windows
                empty_error_ips = []
                for ip, window in self.ip_error_windows.items():
                    while window and window[0] < cutoff:
                        window.popleft()
                    if not window:
                        empty_error_ips.append(ip)
                        
                for ip in empty_error_ips:
                    del self.ip_error_windows[ip]
                    
    def get_current_rates(self):
        """Returns the length of sliding windows for anomaly detection."""
        now = time.time()
        cutoff = now - self.window_size
        
        with self.lock:
            # Strict > cutoff ensures exactly 60 seconds precision
            global_rate = sum(1 for ts in self.global_window if ts >= cutoff)
            ip_rates = {
                ip: sum(1 for ts in window if ts >= cutoff)
                for ip, window in self.ip_windows.items()
            }
            ip_errors = {
                ip: sum(1 for ts in window if ts >= cutoff)
                for ip, window in self.ip_error_windows.items()
            }
            
            return global_rate, ip_rates, ip_errors
            
    def pop_per_second_counts(self, before_timestamp):
        """Extracts and removes per-second aggregates older than given timestamp for baseline processing."""
        extracted_counts = {}
        extracted_errors = {}
        
        with self.lock:
            timestamps = list(self.per_second_counts.keys())
            for ts in timestamps:
                if ts < before_timestamp:
                    extracted_counts[ts] = self.per_second_counts.pop(ts)
                    extracted_errors[ts] = self.per_second_errors.pop(ts, 0)
                    
        return extracted_counts, extracted_errors
