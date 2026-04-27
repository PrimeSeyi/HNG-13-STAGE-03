# Step 2: Log Monitoring & Sliding Windows (Deep Dive & Data Flow)

This document provides a comprehensive, elaborate breakdown of `detector/monitor.py`. It shows exactly how the module fits into the broader system, and follows a step-by-step example with actual data to show how every single function processes it.

---

## The Big Picture: How is it called?

`LogMonitor` is not a standalone script; it is a module designed to be imported. In `main.py` (which we will build later), the flow will look exactly like this:

```python
# Inside main.py
from monitor import LogMonitor
from detector import AnomalyDetector

# 1. Initialize the monitor
monitor = LogMonitor(log_file="/var/log/nginx/hng-access.log")

# 2. Start it (this runs the tailing and cleanup in the background)
monitor.start()

# 3. Other modules will constantly ask the monitor for data
# For example, detector.py will run a loop doing:
global_rate, ip_rates, ip_errors = monitor.get_current_rates()
```

---

## Function-by-Function Flow with Sample Data

Let's trace exactly what happens through all 7 functions in the module when `monitor.start()` is called and Nginx writes a new access log.

### 1. `__init__(self, log_file, window_size=60)`
This is the setup function. It takes the `log_file` path (e.g., `"/var/log/nginx/hng-access.log"`) and prepares the empty arrays in memory before any logs are read.

**What happens:**
It creates empty tracking lists for the 60-second window.
- `self.global_window = deque()`: Will hold timestamps for every single request.
- `self.ip_windows = defaultdict(deque)`: Will group timestamps by IP address.
- `self.ip_error_windows`: Will track timestamps specifically for 4xx and 5xx errors.
- `self.per_second_counts` and `self.per_second_errors`: Empty hash maps to store the total number of requests that happened during an exact 1-second interval.

### 2. `start(self)`
This function is called by the main application to turn on the monitor. 

**What happens:**
It spawns two background "threads" so the rest of the application isn't blocked:
1. Thread A starts running `_tail_log()` indefinitely.
2. Thread B starts running `_cleanup_old_data()` indefinitely.

### 3. `_tail_log(self)`
This function runs infinitely in the background via Thread A. It listens to the `/var/log/nginx/hng-access.log` file natively.

**What happens:**
It uses `subprocess.Popen(['tail', '-F', ...])`. When Nginx receives a request from IP `192.168.1.5`, Nginx writes this JSON line to the log file:
`{"source_ip": "192.168.1.5", "timestamp": "2026-04-27T10:00:00Z", "method": "GET", "path": "/", "status": "200", "response_size": "512"}`

`_tail_log` instantly captures this raw text string and passes it into the next function: `_process_line()`.

### 4. `_process_line(self, line)`
This function takes the raw JSON string passed from `_tail_log` and organizes the data into memory.

**What happens:**
1. It converts the JSON string into a Python dictionary.
2. It extracts `source_ip = "192.168.1.5"` and `status = "200"`.
3. It generates the current Unix timestamp. Let's say right now it is `1700000050`.

It then attaches this timestamp to our tracking lists:
- `self.global_window.append(1700000050)`
- `self.ip_windows["192.168.1.5"].append(1700000050)`
- `self.per_second_counts[1700000050] += 1` (This increments the total requests for this specific second to 1).

If another request comes from `192.168.1.5` one second later (`1700000051`), the tracking list updates:
`self.ip_windows["192.168.1.5"]` becomes `[1700000050, 1700000051]`

### 5. `_cleanup_old_data(self)`
This is a "janitor" function running via Thread B every 5 seconds. Its job is to enforce the **60-second sliding window** limit so memory doesn't explode.

**What happens:**
Let's say the current time is now `1700000120`. 
The cutoff time is `Current Time (1700000120) - 60 seconds = 1700000060`.

The janitor looks at our `192.168.1.5` tracking list:
`[1700000050, 1700000051]`

Because both of these timestamps are *smaller* (older) than the cutoff of `1700000060`, the janitor runs `.popleft()` and deletes them from the array. The array is now completely empty, meaning `192.168.1.5` has `0` requests in the last 60 seconds. Memory is freed.

### 6. `get_current_rates(self)`
This function is publicly exposed so `detector.py` can call it to see if anyone is attacking the server *right now*.

**What happens:**
`detector.py` asks: "How many requests happened in the last 60 seconds?"
1. The function looks at `self.global_window` and counts how many timestamps are currently inside it. Let's say it counts `150`.
2. It looks at `self.ip_windows["192.168.1.5"]` and counts `100`.
3. It returns these numbers. `detector.py` receives: `Global: 150`, `192.168.1.5: 100`.
`detector.py` will then check if 100 requests/min is considered an anomaly based on the baseline.

### 7. `pop_per_second_counts(self, before_timestamp)`
This function is publicly exposed so `baseline.py` can build the 30-minute history for anomaly math.

**What happens:**
`baseline.py` calls this every 60 seconds, passing in a timestamp (e.g., `1700000060`).
Instead of `baseline.py` scanning the raw logs again, it just says: "Give me the total counts for every second that is older than 1700000060, and delete them from your memory."

`monitor.py` finds `self.per_second_counts[1700000050] = 1`, hands it over to `baseline.py`, and deletes it from its own memory hash map. This creates a highly efficient relay where `monitor.py` handles the current 60 seconds, and passes the finalized data backwards to `baseline.py`.

---

## Summary of the Flow
1. **`main.py`** imports and initializes `LogMonitor` with `__init__`.
2. **`main.py`** calls `start()` which kicks off the **`_tail_log`** reader and the **`_cleanup_old_data`** janitor simultaneously in the background.
3. Every time Nginx logs an event, **`_tail_log`** instantly passes it to **`_process_line`** which timestamps it and throws it into the tracking arrays.
4. The **`_cleanup_old_data`** loop aggressively removes timestamps older than 60 seconds to prevent memory leaks.
5. Concurrently, **`get_current_rates`** and **`pop_per_second_counts`** are being called continuously by the Detector and Baseline modules to fetch the live tracking data they need.
