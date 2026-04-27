# Step 5: Live Metrics UI & Main Entrypoint (Comprehensive Deep Dive & Flow)

This document provides a highly elaborate, exhaustive breakdown of every single function across `main.py` and `dashboard.py`. It shows exactly how the modules work together in a pipeline, details every function with sample data, and summarizes the complete lifecycle. No logic is skipped or summarized.

---

## The Big Picture: How is it called?

`main.py` is the absolute entry point of the daemon. You run the daemon via the terminal by executing: `python detector/main.py`. It is responsible for instantiating the entire architecture.

```python
# Provide a concrete code snippet showing the imports and instantiation
from dashboard import Dashboard

# 1. Initialize inside main.py
dashboard = Dashboard(
    monitor=monitor,
    baseline_calc=baseline_calc,
    blocker=blocker,
    config=config
)

# 2. Start processes
dashboard.start()
```

---

## Function-by-Function Flow with Sample Data

### Module 1: `main.py`

#### 1. `main()`
The bootstrapper function that parses configs and launches all threads.

**What happens:**
1. It attempts to read `config.yaml` from the filesystem.
2. It initializes all classes developed in Step 2, 3, 4, and 5 (`LogMonitor`, `BaselineCalculator`, `Notifier`, `Unbanner`, `Blocker`, `AnomalyDetector`, and `Dashboard`), passing references so they can talk to each other.
3. It calls `.start()` on `monitor`, `baseline_calc`, `unbanner`, and `detector`. These four functions spawn daemon threads that run indefinitely in the background.
4. Finally, it calls `dashboard.start()`. Because the Flask server blocks the main thread, the script does not exit, keeping the daemon alive continuously.

**Example:**
The application starts. It reads the Slack URL from config. It spawns 5 background threads (2 for monitor, 1 for baseline, 1 for detector, 1 for unbanner). It then binds port `5000` to `0.0.0.0` and waits for incoming HTTP requests.

---

### Module 2: `dashboard.py`

#### 2. `__init__(self, monitor, baseline_calc, blocker, config)`
Sets up the Flask server and dependency references.

**What happens:**
It saves references to the active modules so it can query live data. It records `self.start_time = time.time()` to act as an anchor point for the uptime calculation. It initializes the Flask `app` object and registers two HTTP routes: `/api/metrics` and `/`.

**Example:**
Inputs are the active `monitor`, `baseline`, and `blocker` instances. It records `start_time = 1700000000`.

#### 3. `get_uptime(self)`
Calculates how long the daemon has been running natively without third-party libraries.

**What happens:**
It calculates the difference in seconds between `time.time()` (now) and `self.start_time`. It uses `divmod` to calculate how many times `3600` fits in the difference (hours), and then uses `divmod` on the remainder to find `minutes` and `seconds`. It formats these integers into a string.

**Example:**
If current time is `1700003665`, the difference is `3665` seconds. `divmod(3665, 3600)` yields `1` hour with a remainder of `65`. `divmod(65, 60)` yields `1` minute and `5` seconds. The function returns `"1h 1m 5s"`.

#### 4. `metrics(self)`
The JSON API endpoint providing the live internal state of the daemon.

**What happens:**
1. Calls `monitor.get_current_rates()` for `global_rate` and `ip_rates`.
2. Calls `baseline_calc.get_baselines()` for the `mean` and `stddev`.
3. Sorts the `ip_rates` dictionary based on the rate value in descending order, then slices the list `[:10]` to extract the Top 10 IP address strings and their rates.
4. Grabs the internal `banned_ips` set from the Blocker and converts it to a standard list.
5. Uses `psutil.cpu_percent()` and `psutil.virtual_memory().percent` to poll system resources.
6. Returns the consolidated dictionary as a JSON HTTP response.

**Example:**
It receives `ip_rates={"192.168.1.5": 20, "10.0.0.1": 5}`. Sorting produces `[("192.168.1.5", 20), ("10.0.0.1", 5)]`. It checks `psutil` and gets CPU `15.5%`. It packages this all into a Python dictionary and outputs the JSON string to the browser.

#### 5. `index(self)`
Serves the user-facing HTML template.

**What happens:**
It outputs a raw HTML string. Embedded inside this HTML is JavaScript using `setInterval(fetchMetrics, 2000)`. Every 2 seconds, the client's browser issues a GET request to `/api/metrics`. The JSON is parsed, and the DOM elements (e.g., `document.getElementById('cpu').innerText = data.cpu_usage;`) are injected with the new data seamlessly without page reloads.

**Example:**
A browser navigates to `http://domain:5000/`. The raw HTML is sent. 2 seconds later, JS fetches `/api/metrics`, receives `{"cpu_usage": 15.5}`, and updates the `<span id="cpu"></span>` to say `15.5`. 

#### 6. `start(self)`
Fires up the Flask application.

**What happens:**
It executes `self.app.run(host, port, debug=False, use_reloader=False)`. Setting `use_reloader=False` is critical; otherwise, Flask spawns duplicate child processes that would cause the background threads (like the monitor) to run twice simultaneously, breaking the logic.

**Example:**
It blocks the python script on port `5000` listening on IP `0.0.0.0`.

---

## Summary of the Complete Lifecycle Flow

1. **`main.py`** initializes `config.yaml` and instantiates all 6 core classes.
2. **`main.py`** calls `start()` on all modules, which spin off 5 independent background threads performing their log tailing, baseline calculating, checking, and unbanning duties continuously.
3. Finally, **`main.py`** calls `dashboard.start()`, which binds a Flask web server to the main thread, keeping the Python process alive indefinitely.
4. When a User navigates to the Dashboard UI, the HTML sends a request to `/api/metrics` every 2 seconds.
5. Concurrently, the API fetches the live metrics from the active background threads (like the current rates from the monitor and the hardware stats from `psutil`) and returns it instantly to the user's screen.
