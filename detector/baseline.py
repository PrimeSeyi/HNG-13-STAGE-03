# Calculates the 30-minute rolling baseline mean and standard deviation.
import math
import time
import threading
import logging

class BaselineCalculator:
    def __init__(self, monitor, history_minutes=30):
        self.monitor = monitor
        self.history_seconds = history_minutes * 60
        
        # Hash maps for the rolling 30-minute window (timestamp -> requests)
        self.history_counts = {}
        self.history_errors = {}
        
        # Hash map for historical per-hour slots (0-23) -> {'mean': X, 'stddev': Y, 'error_rate': Z}
        self.hourly_baselines = {}
        
        # The currently active effective baseline
        self.current_mean = 0.0
        self.current_stddev = 0.0
        self.current_error_rate = 0.0
        
        self.lock = threading.Lock()
        self.running = False

    def start(self):
        """Starts the background thread that recalculates the baseline every 60s."""
        self.running = True
        self.thread = threading.Thread(target=self._recalculate_loop, daemon=True)
        self.thread.start()

    def _recalculate_loop(self):
        """Infinite loop sleeping for 60 seconds before triggering a recalculation."""
        while self.running:
            time.sleep(60)
            self.recalculate()

    def recalculate(self):
        """Fetches data from monitor, cleans old data, and recalculates mean and stddev."""
        now = time.time()
        
        # Fetch per-second counts older than "now" from the monitor
        new_counts, new_errors = self.monitor.pop_per_second_counts(now)
        
        with self.lock:
            # Add new data to our 30-minute history dictionaries
            self.history_counts.update(new_counts)
            self.history_errors.update(new_errors)
            
            # Remove data older than 30 minutes
            cutoff = now - self.history_seconds
            
            old_timestamps = [ts for ts in self.history_counts.keys() if ts < cutoff]
            for ts in old_timestamps:
                del self.history_counts[ts]
                if ts in self.history_errors:
                    del self.history_errors[ts]
            
            # Recalculate Mean and StdDev with the cleaned history
            self._compute_stats(now)

    def _compute_stats(self, now):
        """Computes the mean, standard deviation, and error rate, and updates hourly slots."""
        counts = list(self.history_counts.values())
        n = len(counts)
        
        if n == 0:
            return
            
        # 1. Calculate Mean
        mean = sum(counts) / n
        
        # 2. Calculate Standard Deviation (Sample StdDev)
        if n > 1:
            variance = sum((x - mean) ** 2 for x in counts) / (n - 1)
            stddev = math.sqrt(variance)
        else:
            stddev = 0.0
            
        # 3. Calculate Error Rate (mean error requests per second)
        error_rate = 0.0
        if self.history_errors:
            error_counts = list(self.history_errors.values())
            error_rate = sum(error_counts) / len(error_counts)
            
        # 4. Handle Per-Hour Slots
        current_hour = time.localtime(now).tm_hour
        
        # If we have at least 300 data points (5 minutes), we consider it "enough" to lock in an hourly slot
        has_enough_data = n >= 300
        
        if has_enough_data:
            self.hourly_baselines[current_hour] = {
                'mean': mean,
                'stddev': stddev,
                'error_rate': error_rate
            }
            
        # 5. Decide which baseline to use as "effective"
        # Instruction: "prefer the current hour's baseline when it has enough data"
        if current_hour in self.hourly_baselines:
            slot = self.hourly_baselines[current_hour]
            self.current_mean = slot['mean']
            self.current_stddev = slot['stddev']
            self.current_error_rate = slot['error_rate']
        else:
            # Fallback to the rolling one if the hourly slot isn't ready yet
            self.current_mean = mean
            self.current_stddev = stddev
            self.current_error_rate = error_rate

    def get_baselines(self):
        """Returns the current computed baselines for the detector."""
        with self.lock:
            return self.current_mean, self.current_stddev, self.current_error_rate
