# Step 3: Baseline & Statistics (Deep Dive & Data Flow)

This document provides a comprehensive, elaborate breakdown of `detector/baseline.py`. It shows exactly how the module fits into the broader system, and follows a step-by-step example with actual data to show how every single function processes it.

---

## The Big Picture: How is it called?

`BaselineCalculator` works hand-in-hand with the `LogMonitor` we created in Step 2. In `main.py`, the flow looks exactly like this:

```python
# Inside main.py
from monitor import LogMonitor
from baseline import BaselineCalculator

# 1. Initialize the monitor (Step 2)
monitor = LogMonitor(log_file="/var/log/nginx/hng-access.log")
monitor.start()

# 2. Initialize the baseline calculator, passing in the monitor so it can fetch data
baseline_calc = BaselineCalculator(monitor=monitor, history_minutes=30)

# 3. Start it (this runs the 60-second recalculation loop in the background)
baseline_calc.start()

# 4. Other modules (like the Detector) will ask the baseline for the current math:
mean, stddev, error_rate = baseline_calc.get_baselines()
```

---

## Function-by-Function Flow with Sample Data

Let's trace exactly what happens through all 5 functions in the module when `baseline_calc.start()` is called.

### 1. `__init__(self, monitor, history_minutes=30)`
This is the setup function. It receives the running `monitor` instance so it can talk to it, and prepares memory.

**What happens:**
It creates empty tracking lists for the 30-minute rolling baseline, and the hourly slots.
- `self.history_counts` and `self.history_errors`: Empty hash maps. They will store the requests-per-second totals passed from the monitor.
- `self.hourly_baselines`: An empty hash map that will save baselines keyed by the hour of the day (0 to 23).
- `self.current_mean`, `self.current_stddev`, `self.current_error_rate`: Set to `0.0`. These are the "effective" numbers that the Anomaly Detector will actually use to ban IPs.

### 2. `start(self)`
This function is called by the main application to turn on the calculator. 

**What happens:**
It spawns a background thread running `_recalculate_loop()` indefinitely, ensuring the math is constantly updated without freezing the rest of the application.

### 3. `_recalculate_loop(self)`
This function runs infinitely in the background.

**What happens:**
It runs `time.sleep(60)` to wait for exactly 60 seconds. Once it wakes up, it calls `recalculate()` and goes back to sleep. This precisely fulfills the criteria: *"recalculated every 60 seconds"*.

### 4. `recalculate(self)`
This is the workhorse function. It asks the monitor for data, cleans out old data, and triggers the math.

**What happens:**
Let's say the time right now is `1700000060`.
1. It calls `self.monitor.pop_per_second_counts(1700000060)`. The monitor replies: "Here is what happened in the last 60 seconds. There was 1 request at `1700000050` and 5 requests at `1700000051`."
2. The function adds these to our 30-minute history:
   - `self.history_counts[1700000050] = 1`
   - `self.history_counts[1700000051] = 5`
3. It then deletes any timestamps from `self.history_counts` that are older than 30 minutes (i.e., older than `1700000060 - 1800 seconds = 1699998260`).
4. Finally, it calls `_compute_stats()`.

### 5. `_compute_stats(self, now)`
This function handles the statistics (Mean, Standard Deviation, Error Rate) and the Per-Hour Slots logic.

**What happens:**
1. **Math**: It looks at the history array: `[1, 5]`. 
   - `Mean = (1 + 5) / 2 = 3.0` requests per second.
   - `Variance = ((1 - 3)^2 + (5 - 3)^2) / 1 = 8.0`. `StdDev = sqrt(8) = 2.82`.
2. **Hourly Slot Locking**: It checks the current hour. Let's say it's 2 PM (`14`). It checks if we have at least 5 minutes (300 data points) in our history. If we do, it saves these stats into `self.hourly_baselines[14] = {'mean': 3.0, 'stddev': 2.82, 'error_rate': 0.0}`.
3. **Effective Baseline**: It checks if `self.hourly_baselines[14]` exists. Because it does (we just saved it), it sets `self.current_mean = 3.0` and `self.current_stddev = 2.82`.

### 6. `get_baselines(self)`
This function is publicly exposed so `detector.py` can grab the current thresholds to check if an IP is attacking.

**What happens:**
`detector.py` asks: "What is the baseline right now?"
This function immediately returns `(3.0, 2.82, 0.0)`.
`detector.py` will then check if the IP's request rate exceeds `Mean + (3 * StdDev)` (Z-score > 3.0) or `Mean * 5` (Multiplier > 5x).

---

## Summary of the Flow
1. **`main.py`** imports and initializes `BaselineCalculator` and connects it to the `LogMonitor`.
2. **`main.py`** calls `start()` which kicks off the **`_recalculate_loop`** sleeping for 60 seconds.
3. Every 60 seconds, **`recalculate`** fetches exactly 60 seconds of aggregated data from the Monitor and merges it into a 30-minute rolling hash map.
4. Old data (older than 30 minutes) is deleted to preserve memory.
5. **`_compute_stats`** runs the math. If the data is thick enough (>5 minutes), it locks the math into the **Current Hour Slot**.
6. The Detector module continuously calls **`get_baselines`** to enforce bans based on these calculated thresholds.
