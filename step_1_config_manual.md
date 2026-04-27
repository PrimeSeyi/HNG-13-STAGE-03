# Step 1: Detector Directory Structure & Configurations Plan

Based on the instructions provided, this document outlines the complete plan for setting up the directory structure and the configurations for the anomaly detection daemon.

## Directory Structure

We will adhere exactly to the required repository structure using Python.

```text
HNG-14-03/
├── detector/
│   ├── main.py           # Entry point; initializes and runs all threads/async tasks
│   ├── monitor.py        # Tails Nginx logs natively and parses JSON lines
│   ├── baseline.py       # Calculates 30-minute rolling baseline (mean & stddev)
│   ├── detector.py       # Compares 60s sliding window against baselines
│   ├── blocker.py        # Adds/removes iptables rules to drop IPs
│   ├── unbanner.py       # Tracks ban durations and handles backoff auto-unban schedule
│   ├── notifier.py       # Triggers Slack webhook alerts on bans/unbans
│   ├── dashboard.py      # Flask/FastAPI server for Live Metrics UI (refresh < 3s)
│   ├── config.yaml       # Core configuration file for the daemon
│   ├── requirements.txt  # Python dependencies (e.g., PyYAML, flask, requests, psutil)
│   └── Dockerfile        # Containerizes the Python Daemon for deployment
├── nginx/
│   └── nginx.conf        # Nginx reverse proxy configuration with JSON access logs
└── docs/
    └── architecture.png  # Diagram representing the system flow (to be added)
```

## Module Responsibilities

### `detector/config.yaml`
This file will serve as the single source of truth for configurable variables in the daemon.

**Proposed Configuration:**
```yaml
app:
  log_file: "/var/log/nginx/hng-access.log"
  audit_log: "/var/log/nginx/detector-audit.log"
  window_size_seconds: 60
  baseline_history_minutes: 30

thresholds:
  z_score_limit: 3.0
  rate_multiplier_limit: 5.0
  error_surge_multiplier: 3.0

backoff_schedule:
  - 600      # 10 minutes (in seconds)
  - 1800     # 30 minutes
  - 7200     # 2 hours
  - -1       # Permanent (-1 indicates no expiration)

slack:
  webhook_url: "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

dashboard:
  host: "0.0.0.0"
  port: 5000
```

### `detector/requirements.txt`
Dependencies required to run the daemon effectively:
- `PyYAML` (For parsing config.yaml)
- `flask` (For the web dashboard)
- `requests` (For the Slack notifier webhook)
- `psutil` (For fetching CPU and memory usage in the dashboard)

### Role Breakdown

1. **`main.py`**: Reads `config.yaml`. Sets up the shared deque structures. Spawns threads or asyncio tasks for `monitor`, `baseline`, `unbanner`, and `dashboard`.
2. **`monitor.py`**: Executes an efficient, non-blocking tail on `app.log_file`. Maintains the 60-second deques of timestamps for global and per-IP requests.
3. **`baseline.py`**: Every 60 seconds, computes `mean` and `stddev` of request rates from the past 30 minutes. Retains per-hour slots.
4. **`detector.py`**: Hooked into `monitor.py`'s read loop (or running periodically), checks if global or per-IP rates exceed `thresholds`. Triggers `blocker` and `notifier`.
5. **`blocker.py`**: Executes `sudo iptables -A INPUT -s <IP> -j DROP`. Writes to `app.audit_log`. 
6. **`unbanner.py`**: Runs a loop checking if any banned IP has exceeded its time based on `backoff_schedule`. Deletes iptables rules and calls `notifier`.
7. **`notifier.py`**: Formats the payload (condition fired, current rate, baseline, timestamp, duration) and sends a POST request to `slack.webhook_url`.
8. **`dashboard.py`**: Serves the UI. Uses a background task or queries the shared state from other modules to render CPU usage, baselines, and banned IPs.

## Next Steps
Once you review and approve this configuration and structural plan, we can proceed to automatically create the `detector/` directory and populate `config.yaml` and `requirements.txt` to begin the development of the Python modules.
