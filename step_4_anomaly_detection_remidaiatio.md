# Step 4: Anomaly Detection & Remediation (Comprehensive Deep Dive & Flow)

This document provides a highly elaborate, exhaustive breakdown of every single function across all four modules comprising the Remediation Engine: `detector.py`, `blocker.py`, `unbanner.py`, and `notifier.py`. It shows exactly how the modules work together in a pipeline, details every function with sample data, and summarizes the complete lifecycle.

---

## The Big Picture: How is it called?

In `main.py`, these modules are stitched together like a pipeline. The flow will look exactly like this:

```python
# Inside main.py
from monitor import LogMonitor
from baseline import BaselineCalculator
from unbanner import Unbanner
from blocker import Blocker
from notifier import Notifier
from detector import AnomalyDetector
import yaml

# Load thresholds and Slack URL from config.yaml
with open("detector/config.yaml") as f:
    config = yaml.safe_load(f)

# 1. Initialize auxiliary tools
notifier = Notifier(webhook_url=config['slack']['webhook_url'])
unbanner = Unbanner(backoff_schedule=config['backoff_schedule'], notifier=notifier)
blocker = Blocker(unbanner=unbanner, audit_log_path=config['app']['audit_log'])

# 2. Initialize the core detection engine
detector = AnomalyDetector(
    monitor=monitor, 
    baseline_calc=baseline_calc, 
    blocker=blocker, 
    notifier=notifier, 
    thresholds=config['thresholds']
)

# 3. Start the background processes
unbanner.start()
detector.start()
```

---

## Module 1: `detector.py`
This module acts as the central brain. It continuously fetches data from the Monitor and Baseline, evaluates mathematical thresholds, and commands the other modules to act.

### 1. `__init__(self, monitor, baseline_calc, blocker, notifier, thresholds)`
This setup function injects all the necessary dependencies so the Detector can communicate with the rest of the application.

**What happens:**
It stores references to `monitor`, `baseline_calc`, `blocker`, and `notifier`. It extracts the raw mathematical limits from the `config.yaml` dictionary.
**Example:**
It sets `self.z_limit = 3.0` (Z-score limit), `self.rate_limit = 5.0` (5x multiplier limit), and `self.error_surge = 3.0` (3x multiplier for errors).

### 2. `start(self)`
This function is called by `main.py` to activate the anomaly detection engine.

**What happens:**
It sets a flag `self.running = True` and spawns a background thread that executes `_detection_loop()`. This ensures the main application thread is never blocked.

### 3. `_detection_loop(self)`
This is the infinite loop running in the background thread.

**What happens:**
It executes `time.sleep(2)`, pausing for exactly 2 seconds, and then calls `self.detect()`.
**Example:**
If the server starts at `10:00:00`, it sweeps for anomalies at `10:00:02`, `10:00:04`, `10:00:06`, etc. This fulfills the requirement that the system responds within 10 seconds of an attack starting.

### 4. `detect(self)`
This function orchestrates the data gathering. It fetches live data and mathematical baselines, and determines if a check is necessary.

**What happens:**
1. It calls `self.monitor.get_current_rates()`. It receives the Global rate, a dictionary of per-IP rates, and a dictionary of per-IP error rates.
2. It calls `self.baseline_calc.get_baselines()`. It receives the Mean, Standard Deviation, and Baseline Error Rate.
3. If the Mean is `0.0`, it aborts immediately because the baseline is not fully formed yet.
4. It calls `_check_anomaly` passing in `"GLOBAL"` and the global rate.
5. It loops over every single IP in the `ip_rates` dictionary. It checks if the IP is already blocked (`self.blocker.is_banned(ip)`). If it is, it skips it. Otherwise, it passes the IP's specific data into `_check_anomaly`.
**Example:**
At `10:00:02`, `detect()` discovers `ip_rates` contains `{"192.168.1.5": 20}`. The `blocker` confirms `192.168.1.5` is not banned. It fetches the baseline (Mean `3.0`, StdDev `2.82`) and passes all this to `_check_anomaly`.

### 5. `_check_anomaly(self, entity, current_rate, mean, stddev, ip_error_rate, baseline_error_rate)`
This is the core mathematical engine. It calculates the Z-Score and assesses the multipliers.

**What happens:**
1. **Calculate Z-Score**: It computes `(current_rate - mean) / stddev`.
2. **Error Surge Rule**: It checks if the IP is throwing 4xx/5xx errors at a rate greater than `baseline_error_rate * self.error_surge` (e.g., > 3x the baseline). If so, it cuts `self.z_limit` and `self.rate_limit` exactly in half.
3. **Condition Triggers**: It checks if the calculated Z-score is greater than the active Z-limit, OR if the `current_rate` is greater than `mean * active_rate_limit`.
4. **Action**: If a condition triggers, it branches. If the entity is `"GLOBAL"`, it only triggers `self.notifier.send_alert`. If the entity is an IP, it calls `self.blocker.ban_ip` and then `self.notifier.send_alert`.
**Example:**
Entity is `"192.168.1.5"`. `current_rate` is `20`. `mean` is `3.0`. `stddev` is `2.82`. `ip_error_rate` is `6`. `baseline_error_rate` is `0.5`.
Because `6` is greater than `0.5 * 3.0 (1.5)`, the Error Surge engages. The Z-limit drops from `3.0` to `1.5`. 
Z-score is calculated: `(20 - 3.0) / 2.82 = 6.02`. 
Because `6.02 > 1.5`, `is_anomalous` becomes `True`. It triggers `self.blocker.ban_ip` with the exact condition string: `"Z-Score 6.02 > 1.50"`.

---

## Module 2: `blocker.py`
This module interacts directly with the Linux operating system to enforce network drops. It also manages the official Audit Log.

### 1. `__init__(self, unbanner, audit_log_path)`
This setup function receives the `unbanner` instance and sets up tracking lists.

**What happens:**
It creates an empty set `self.banned_ips = set()` to track who is currently blocked in memory, preventing redundant `iptables` commands. It saves the `audit_log_path` (e.g., `"/var/log/nginx/detector-audit.log"`).

### 2. `is_banned(self, ip)`
A simple, publicly exposed checker function used by `detector.py`.

**What happens:**
It returns `True` if the requested IP exists inside `self.banned_ips`, otherwise `False`.
**Example:**
`detector.py` asks `is_banned("192.168.1.5")`. Because the set is currently empty, it returns `False`.

### 3. `ban_ip(self, ip, condition, rate, baseline)`
This is the physical execution function that blocks an IP address.

**What happens:**
1. It calls `self.unbanner.get_ban_duration(ip)` to figure out how many seconds this ban should last.
2. It uses `subprocess.run` to execute `sudo iptables -I DOCKER-USER -s <ip> -j DROP` on the host machine.
3. It adds the IP to the `self.banned_ips` set.
4. If the duration is not permanent (`-1`), it calls `self.unbanner.schedule_unban` so the IP will eventually be released.
5. It calls `_write_audit()` to log the ban.
**Example:**
Input is `ip="192.168.1.5"`, `condition="Z-Score 6.02 > 1.50"`, `rate=20`, `baseline=3.0`. 
`unbanner.get_ban_duration` tells it the ban should last `600` seconds.
It runs `sudo iptables -I DOCKER-USER -s 192.168.1.5 -j DROP`. It adds `192.168.1.5` to the set. It tells the unbanner to schedule an unban for `600` seconds from now. It writes to the audit log.

### 4. `_write_audit(self, action, ip, condition, rate, baseline, duration)`
This function is strictly responsible for formatting the text written to the physical log file on the disk.

**What happens:**
It grabs the current Unix time and converts it to a strict ISO8601 string. It formats a string exactly matching the required criteria: `[timestamp] ACTION ip | condition | rate | baseline | duration`. It opens the file in append (`'a'`) mode and writes the line.
**Example:**
It generates the string: `[2026-04-27T10:00:02Z] BAN 192.168.1.5 | Z-Score 6.02 > 1.50 | 20 | 3.00 | 600\n` and appends it to `/var/log/nginx/detector-audit.log`.

### 5. `unban_ip_manually(self, ip)`
This function reverses the `iptables` rule. It is designed to be called by `unbanner.py` when a countdown expires.

**What happens:**
It verifies the IP is in `self.banned_ips`. It executes `sudo iptables -D DOCKER-USER -s <ip> -j DROP`. It removes the IP from the set, and calls `_write_audit` to log the `UNBAN` action.
**Example:**
Input is `192.168.1.5`. It executes `sudo iptables -D DOCKER-USER -s 192.168.1.5 -j DROP`. It removes the IP from the internal set. It writes `[2026-04-27T10:10:02Z] UNBAN 192.168.1.5 | Schedule Expired | 0 | 0.00 | 0` to the audit log.

---

## Module 3: `unbanner.py`
This module tracks the escalating backoff schedule and manages the background countdown timers to release IPs.

### 1. `__init__(self, backoff_schedule, notifier)`
The setup function initializes the schedule rules and empty memory structures.

**What happens:**
It stores `backoff_schedule` (e.g., `[600, 1800, 7200, -1]`).
It creates `self.ip_offense_counts = {}` to track how many times a specific IP has attacked.
It creates `self.scheduled_unbans = {}` to track exact future timestamps of when an IP should be unbanned.

### 2. `start(self)`
Called by `main.py` to activate the auto-unban engine.

**What happens:**
It spawns a background thread running `_unban_loop()` indefinitely.

### 3. `get_ban_duration(self, ip)`
Called by `blocker.py` *before* a ban is applied, to determine how severe the ban should be.

**What happens:**
It checks `self.ip_offense_counts`. If the IP has never attacked, offenses = 0. It grabs `backoff_schedule[0]` (10 minutes). It then increments the offense count for that IP by 1, so the *next* time it attacks, it will get a harsher penalty. If the IP has exhausted the list, it returns the final permanent value (`-1`).
**Example:**
Input is `192.168.1.5`. `self.ip_offense_counts` is empty. It returns `backoff_schedule[0]` which is `600`. It updates `self.ip_offense_counts["192.168.1.5"] = 1`. Next time this IP attacks, it will return `1800`.

### 4. `schedule_unban(self, ip, duration_seconds, blocker_ref)`
Called by `blocker.py` *after* a ban is applied, to set the timer.

**What happens:**
It calculates the exact future Unix timestamp: `Current Time + duration_seconds`. It stores this timestamp in the dictionary. It dynamically stores the `blocker_ref` so it knows who to call when the time is up.
**Example:**
Current time is `1700000000`. Duration is `600`. It calculates `1700000600`. It sets `self.scheduled_unbans["192.168.1.5"] = 1700000600`.

### 5. `_unban_loop(self)`
This is the infinite loop running in the background thread.

**What happens:**
It sleeps for 5 seconds. It iterates over every IP in `self.scheduled_unbans`. If the current Unix time is greater than or equal to the scheduled unban time, it triggers the release. It calls `self.blocker.unban_ip_manually(ip)`. If successful, it deletes the IP from the schedule dictionary and calls `self.notifier.send_alert` to notify Slack.
**Example:**
Current time hits `1700000601`. It sees that `1700000601 >= 1700000600`. It calls `blocker.unban_ip_manually("192.168.1.5")`. It deletes the entry from `self.scheduled_unbans`. It pings Slack that the IP was automatically unbanned.

---

## Module 4: `notifier.py`
This module handles all external communication via Slack Webhooks.

### 1. `__init__(self, webhook_url)`
The setup function.

**What happens:**
It simply stores the Slack `webhook_url` provided by `config.yaml`.

### 2. `send_alert(self, ip, condition, rate, baseline, duration)`
This function builds a rich message block and executes the HTTP POST request to Slack.

**What happens:**
1. It immediately aborts if no webhook URL is configured.
2. It formats the duration string (e.g., translating `-1` to `"Permanent"`).
3. It constructs a multi-line formatted string using Slack's markdown (bolding fields with `*`).
4. It wraps the string in a dictionary: `{"text": message}`.
5. It executes `requests.post(url, json=payload, timeout=5)`. A 5-second timeout ensures that if Slack is down, the daemon thread does not hang indefinitely. If an exception occurs, it fails silently, ensuring the security system never crashes due to a chat app outage.
**Example:**
It generates the message:
`🚨 *Security Alert*`
`• *Action/IP*: 192.168.1.5`
`• *Condition Fired*: Z-Score 6.02 > 1.50`
`• *Current Rate*: 20 req/s`
`• *Baseline*: 3.00 req/s`
`• *Ban Duration*: 600s`
`• *Timestamp*: 2026-04-27T10:00:02Z`
It sends this block as JSON to `https://hooks.slack.com/services/...` which instantly appears in your Slack channel.

---

## Summary of the Complete Lifecycle Flow
1. **`main.py`** initializes the auxiliary tools (`Notifier`, `Unbanner`, `Blocker`) and injects them into the **`AnomalyDetector`**.
2. **`detector.py`** continuously checks the math every 2 seconds by pulling the `current_rate` from the Monitor and the `mean/stddev` from the Baseline.
3. If the math triggers (adjusting dynamically for Error Surges), the Detector hands the IP to **`blocker.py`**.
4. **`blocker.py`** executes the `iptables` drop, writes the Audit log, and asks **`unbanner.py`** to start a countdown timer.
5. Concurrently, **`notifier.py`** fires off the Slack webhook so you are instantly informed of the ban.
6. Once the 10-minute countdown expires, **`unbanner.py`** reverses the `iptables` drop and pings Slack with an unban notification.
