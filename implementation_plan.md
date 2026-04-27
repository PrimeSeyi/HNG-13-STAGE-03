# Implementation Plan: Anomaly Detection Daemon

This document outlines the detailed architecture and implementation steps to build the Python-based anomaly detection daemon that runs alongside Nextcloud. The daemon will monitor Nginx logs, calculate traffic baselines, detect anomalies, block malicious IPs, send Slack alerts, and serve a live metrics UI.

## Goal Description

Build a highly-performant Python daemon (`detector`) that:
1. Continuously tails the JSON Nginx access logs.
2. Maintains 60-second sliding windows for request rates (global and per IP) using native Python `deque`.
3. Calculates a 30-minute rolling baseline of traffic (mean and standard deviation).
4. Dynamically bans IPs via `iptables` that exceed the anomaly thresholds (Z-score > 3.0 or 5x baseline) and applies backoff unbanning.
5. Monitors 4xx/5xx error surges to aggressively tighten thresholds.
6. Notifies a Slack channel on bans and unbans.
7. Exposes a live, fast-refreshing (every 3s) dashboard for monitoring.

## User Review Required
> [!IMPORTANT]
> The Live Metrics UI requires a domain or subdomain for grading, while Nextcloud itself will be IP only. We need to plan how Nginx will route the domain traffic to the Python daemon's web server.
> We also need a Slack Webhook URL to configure the alerts. Do you have a URL ready, or should I leave a placeholder in the configuration file?

## Proposed Changes

### 1. Detector Directory Structure & Configurations

We will use Python. A `requirements.txt` will be minimal, likely just `flask` (or `fastapi`), `psutil` (for CPU/Mem), and `requests`.

#### [NEW] `detector/config.json`
- Stores Slack webhook URL.
- Stores threshold defaults (e.g., z_score limit, multiplier limit).

#### [NEW] `detector/main.py`
- The entry point for the daemon.
- Initializes threads/async tasks: Log Tailer, Baseline Recalculator, Unban Scheduler, and Web UI server.

### 2. Log Monitoring & Sliding Windows

#### [NEW] `detector/monitor.py`
- Continuously tails `/var/log/nginx/hng-access.log` using a non-blocking file read (e.g., `subprocess.Popen(['tail', '-F'])` or a python tail generator).
- Parses JSON log lines natively.
- Feeds data into sliding windows.
- Maintains `collections.deque` instances to track timestamps of requests over the last 60 seconds (both globally and per-IP).

### 3. Baseline & Statistics

#### [NEW] `detector/baseline.py`
- Aggregates the per-second counts into rolling 30-minute arrays.
- Computes `mean` and `stddev` every 60 seconds.
- Maintains per-hour slots for historical data to prefer current hour's baseline.
- Tracks baseline error rate for 4xx/5xx requests.

### 4. Anomaly Detection & Remediation

#### [NEW] `detector/detector.py`
- Evaluates the current 60s sliding window rates against the calculated baselines.
- Checks `Z-score = (current_rate - mean) / stddev`. If > 3.0, trigger.
- Checks if `current_rate > 5 * mean`.
- Tightens thresholds if an IP’s error rate hits 3x the baseline error rate.
- Interacts with `iptables` to block IPs via shell commands (e.g., `subprocess.run(['iptables', '-A', ...])`).
- Tracks ban records and manages the backoff schedule (10m -> 30m -> 2h -> Permanent).
- Unbans IPs by deleting the `iptables` rule.
- Appends to the structured audit log.
- Triggers Slack alerts with the required format: `condition fired`, `current rate`, `baseline`, `timestamp`, `ban duration`.

### 5. Web UI Dashboard

#### [NEW] `detector/web.py`
- A lightweight Flask server.
- Exposes a single `/` HTML page.
- Exposes an `/api/metrics` JSON endpoint that returns:
  - Banned IPs
  - Global req/s
  - Top 10 source IPs
  - CPU/memory usage
  - Effective mean/stddev
  - Uptime
- The HTML page uses pure JavaScript with `setInterval` to fetch from `/api/metrics` every 3 seconds and update the DOM dynamically without page reloads.

### 6. Updates to Provisioning

#### [MODIFY] `docker-compose.yml` & `nginx.conf`
- We will need to map a volume/network so the daemon can read the logs. Our current `provision.sh` runs the detector as a docker container.
- **Important**: The Python daemon needs to execute `iptables` on the host machine to block the IPs effectively from reaching Nginx. If the daemon runs inside a Docker container, it needs `NET_ADMIN` capabilities and the host network (`network_mode: host`), or we run the Python daemon directly as a `systemd` service on the Linux host itself.

## Verification Plan

### Automated / Manual Tests
1. Generate normal traffic to Nextcloud using `curl` or a load testing tool to establish a baseline.
2. Verify that `baseline.py` accurately calculates mean/stddev after enough requests.
3. Simulate an attack (e.g., using `hey` or `apachebench`) with a high request rate from a specific IP.
4. Confirm `iptables` rule is added.
5. Confirm Slack webhook triggers.
6. Ensure the live dashboard reflects the banned IP and elevated traffic.
7. Wait 10 minutes and confirm the IP is automatically unbanned and a Slack alert is sent.
