# HNG Anomaly Detection Daemon

A production-grade, real-time anomaly detection engine built to protect a Nextcloud cloud storage platform. It continuously monitors Nginx access logs, learns what "normal" traffic looks like using rolling statistical baselines, and automatically blocks malicious IPs via host-level `iptables` rules when traffic deviates from the norm.

## Live Deployment

| Resource | URL |
|----------|-----|
| **Server IP** | `20.169.136.102` |
| **Metrics Dashboard** | `http://nepobaby.eastus.cloudapp.azure.com` |
| **Nextcloud** | `http://20.169.136.102` (IP-only access) |
| **GitHub Repository** | [github.com/PrimeSeyi/HNG-13-STAGE-03](https://github.com/PrimeSeyi/HNG-13-STAGE-03) |

---

## Language Choice: Python

Python was chosen for several reasons:

1. **Threading model** — Python's `threading` module with daemon threads allows the monitor, baseline calculator, detector, and unbanner to all run concurrently without blocking the Flask dashboard. Each module is a self-contained background thread.
2. **Deque from collections** — Python's `collections.deque` is implemented in C and provides O(1) append and popleft operations, which is exactly what a sliding window needs.
3. **Ecosystem** — `PyYAML` for config parsing, `Flask` for the dashboard, `requests` for Slack webhooks, `psutil` for CPU/memory metrics — all available with no compilation overhead.
4. **Subprocess for iptables** — `subprocess.run()` gives direct, synchronous control over `iptables` commands with proper error handling via `check=True`.

---

## How the Sliding Window Works

The sliding window lives in `detector/monitor.py`. It uses two `collections.deque` structures to track request rates over the last 60 seconds.

### Data Structure

```python
from collections import deque

# Global window: stores (timestamp, status_code) for every request
self.global_window = deque()

# Per-IP window: dict of { ip_address: deque of (timestamp, status_code) }
self.ip_windows = defaultdict(deque)
```

### How Requests Enter the Window

The `_tail_log()` method runs in an infinite background thread. It opens `/var/log/nginx/hng-access.log` and reads new lines as Nginx writes them. Each line is a JSON object:

```json
{"source_ip": "192.168.1.5", "timestamp": "2026-04-27T12:00:01+00:00", "method": "GET", "path": "/login", "status": "200", "response_size": "3419"}
```

For every new line parsed, the monitor appends a `(timestamp, status_code)` tuple to both the global deque and the IP-specific deque.

### Eviction Logic

Every time `get_current_rates()` is called (by the detector, every 2 seconds), the monitor runs `_cleanup_windows()`. This function walks through each deque and pops entries older than 60 seconds:

```python
def _cleanup_windows(self):
    cutoff = time.time() - self.window_size  # window_size = 60 seconds

    # Evict old entries from the global window
    while self.global_window and self.global_window[0][0] < cutoff:
        self.global_window.popleft()

    # Evict old entries from each IP's window
    for ip in list(self.ip_windows.keys()):
        while self.ip_windows[ip] and self.ip_windows[ip][0][0] < cutoff:
            self.ip_windows[ip].popleft()
        if not self.ip_windows[ip]:
            del self.ip_windows[ip]  # Remove empty IP entries entirely
```

Because `deque.popleft()` is O(1), this cleanup is extremely fast even under high traffic. The result is that at any given moment, both deques contain only the requests from the last 60 seconds — nothing older.

### What `get_current_rates()` Returns

```python
global_rate = len(self.global_window)           # Total requests in 60s
ip_rates = {ip: len(dq) for ip, dq in self.ip_windows.items()}  # Per-IP counts
ip_errors = {ip: count_of_4xx_5xx for ...}      # Per-IP error counts
```

---

## How the Baseline Works

The baseline lives in `detector/baseline.py`. It computes a rolling statistical model of what "normal" traffic looks like.

### Window Size and Recalculation Interval

- **Window**: 30 minutes of history, stored as per-second request counts
- **Recalculation**: Every 60 seconds, the baseline thread wakes up, reads the monitor's current global rate, appends it to its history, and recomputes `mean` and `stddev`
- **Per-hour slots**: The baseline maintains separate slots for each hour. When enough data exists for the current hour, it prefers that slot over the global average. This accounts for natural traffic patterns (e.g., more traffic at 2pm than 3am)

### Calculation

```python
import statistics

def _recalculate(self):
    # self.history is a deque of per-second counts from the last 30 minutes
    if len(self.history) < 2:
        return
    self.mean = statistics.mean(self.history)
    self.stddev = statistics.stdev(self.history)
```

### Floor Values and Safety Nets

To prevent false positives, especially during periods of zero traffic where mathematics break down (division by zero), the system enforces strict floor values:

1. **Trivial Traffic Ignore**: If an IP's current rate is less than `1.0` request per second (meaning fewer than 60 requests in the last minute), the detector completely ignores it. This ensures normal users browsing the site are never evaluated for an anomaly.
2. **Standard Deviation Floor**: The standard deviation is mathematically floored to a minimum of `0.5`. If the server is completely idle (stddev = 0.0), any single request would normally trigger an "Infinity" Z-score. The `0.5` floor guarantees that small traffic bursts on an idle server won't trigger instant bans.
3. **Mean Floor**: For the Rate Multiplier calculation (`current_rate > mean * 5`), the mean is floored to a minimum of `1.0`.

The mean is never allowed to be used for detection until at least 60 seconds of data has been collected (the first baseline cycle). Before that, `get_baselines()` returns `mean=0.0`, which causes `detector.py` to skip all anomaly checks with an early `return`.

---

## Architecture

See the full Mermaid diagram in [`docs/architecture.md`](docs/architecture.md).

The system is composed of 8 Python modules orchestrated by `main.py`:

```
main.py ──► monitor.py    (tails log, fills deques)
        ──► baseline.py   (computes rolling mean/stddev)
        ──► detector.py   (z-score + rate checks every 2s)
        ──► unbanner.py   (backoff timers for auto-unban)
        ──► dashboard.py  (Flask UI on port 5000)

detector.py ──► blocker.py   (iptables DROP + audit log)
            ──► notifier.py  (Slack webhook alerts)
```

---

## Setup Instructions (Fresh VPS to Fully Running Stack)

### Prerequisites

- A Linux VPS with at least 2 vCPU and 2 GB RAM (Ubuntu 22.04 recommended)
- Port 80 open in your cloud provider's firewall/NSG
- A domain or subdomain pointing to your server's IP (for the dashboard)
- Git installed on the server

### Step 1: Install Docker

```bash
ssh ubuntu@YOUR_SERVER_IP

sudo apt-get update -y
sudo apt-get install -y ca-certificates curl gnupg

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor --batch --yes -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update -y
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### Step 2: Clone and Configure

```bash
git clone https://github.com/PrimeSeyi/HNG-13-STAGE-03.git ~/HNG-13-STAGE-03
cd ~/HNG-13-STAGE-03

# Inject the real Slack webhook (never commit this — it stays on the server only)
# sed -i 's|YOUR/WEBHOOK/URL|YOUR_REAL_SLACK_WEBHOOK_HERE|' detector/config.yaml
sed -i 's|YOUR/WEBHOOK/URL|YOUR_REAL_SLACK_WEBHOOK_HERE|' detector/config.yaml
```

### Step 3: Deploy

```bash
sudo docker compose up --build -d
```

This will:
- Pull the `kefaslungu/hng-nextcloud` image
- Pull `mariadb:10.6` and `nginx:latest`
- Build the Python detector container from `detector/Dockerfile`
- Create the `HNG-nginx-logs` shared volume
- Start all 4 containers

### Step 4: Verify

```bash
# All 4 containers should be running
sudo docker ps

# Nextcloud should respond on the server IP
curl -s -o /dev/null -w "%{http_code}" http://YOUR_SERVER_IP/

# Dashboard should respond on port 5000
curl -s http://localhost:5000/api/metrics

# Detector logs should show "Starting Anomaly Detection Daemon..."
sudo docker logs $(sudo docker ps -qf "name=detector") --tail 10
```



---

## Configuration Reference

All tunable parameters live in `detector/config.yaml`:

```yaml
app:
  log_file: "/var/log/nginx/hng-access.log"
  audit_log: "/app/detector-audit.log"
  window_size_seconds: 60
  baseline_history_minutes: 30

thresholds:
  z_score_limit: 3.0
  rate_multiplier_limit: 5.0
  error_surge_multiplier: 3.0

backoff_schedule:
  - 600      # 10 minutes
  - 1800     # 30 minutes
  - 7200     # 2 hours
  - -1       # Permanent

slack:
  webhook_url: "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

dashboard:
  host: "0.0.0.0"
  port: 5000
```

---

## Repository Structure

```
HNG-13-STAGE-03/
├── detector/
│   ├── main.py           # Entry point; initializes and runs all threads
│   ├── monitor.py        # Tails Nginx log; sliding window with deques
│   ├── baseline.py       # Rolling 30-min mean/stddev calculator
│   ├── detector.py       # Z-score and rate anomaly engine
│   ├── blocker.py        # iptables DOCKER-USER chain management
│   ├── unbanner.py       # Backoff schedule timer for auto-unban
│   ├── notifier.py       # Slack webhook POST with logging
│   ├── dashboard.py      # Flask live metrics UI
│   ├── config.yaml       # All thresholds, paths, and webhook URL
│   ├── requirements.txt  # Python dependencies
│   └── Dockerfile        # Container build for the daemon
├── nginx/
│   └── nginx.conf        # Reverse proxy with JSON log format
├── docs/
│   ├── architecture.png  # System architecture diagram
│   └── architecture.md   # Mermaid source for the architecture
├── screenshots/          # Required grading screenshots
├── docker-compose.yml    # Full stack orchestration
└── README.md             # This file
```

---

## Blog Post

https://medium.com/@ibrowizzy93/building-an-ai-style-anomaly-detector-from-scratch-a-beginners-guide-to-protecting-your-cloud-662ce3c07b6a
