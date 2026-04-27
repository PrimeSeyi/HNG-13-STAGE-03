# Step 99: Debug & Test (Comprehensive Deep Dive & Flow)

This document provides a highly elaborate, exhaustive breakdown of the debugging phase conducted directly on the remote Linux server (`20.169.136.102`). It shows exactly what bugs were discovered during live traffic simulation, what code was modified to fix them, and why. No logic is skipped or summarized.

---

## The Big Picture: How is it called?

During the live deployment, a simulated DDoS attack (firing 300+ requests simultaneously) was launched against the remote server. The mathematical anomaly engine detected the spike perfectly, but two silent failures occurred in the execution layer: the Slack webhook failed silently, and the Audit Log failed to write.

We diagnosed these issues by injecting Python `logging` statements into the live container and tracing the stack errors.

```python
# The new standard for all modules is to use standard logging instead of silent failures
import logging
logging.basicConfig(level=logging.INFO)

# Example of the new error capture
try:
    execute_action()
    logging.info("Action succeeded")
except Exception as e:
    logging.error(f"Action failed: {e}")
```

---

## Function-by-Function Flow with Sample Data

### 1. `detector/config.yaml` (The Audit Log Path Fix)
The configuration file was modified to bypass a Docker permission conflict.

**What was there before:**
```yaml
app:
  audit_log: "/var/log/nginx/detector-audit.log"
```

**What it was changed to:**
```yaml
app:
  audit_log: "/app/detector-audit.log"
```

**What happens:**
In `docker-compose.yml`, we intentionally mounted the Nginx log volume `/var/log/nginx` as **Read-Only** (`:ro`) so the detector could never accidentally corrupt Nginx's system logs. However, `blocker.py` was instructed to write its `detector-audit.log` into that exact same directory. When it attempted to open the file in append mode (`'a'`), Linux threw an `[Errno 30] Read-only file system` error, causing the audit system to crash.
By changing the path to `/app/detector-audit.log`, the daemon now safely writes the audit log directly into its own isolated, writable container directory.

**Example:**
The detector triggers a ban. Instead of crashing against a read-only mount, it writes `[2026-04-27T13:12:24Z] BAN 192.168.1.5 | ...` directly to `/app/detector-audit.log` inside the container memory.

### 2. `detector/notifier.py` (The Silent Failure Fix)
This module was updated to prevent errors from being swallowed into the void.

**What was there before:**
```python
        try:
            requests.post(self.webhook_url, json=payload, timeout=5)
        except Exception:
            pass # Fail silently
```

**What it was changed to:**
```python
        try:
            r = requests.post(self.webhook_url, json=payload, timeout=5)
            logging.info(f'Slack alert sent for {ip}: status={r.status_code} response={r.text}')
        except Exception as e:
            logging.error(f'Slack alert FAILED for {ip}: {e}')
```

**What happens:**
Because we stripped out your real Slack Webhook URL to bypass GitHub's Secret Scanning (replacing it with `YOUR/WEBHOOK/URL`), the `requests.post` function threw an Invalid URL exception. Because the original code had a bare `pass` statement, the daemon swallowed the error and continued running, leaving us completely blind as to why Slack wasn't pinging.
The function now actively logs the exact HTTP status code returned by Slack (e.g., `200 OK`) and prints a loud, visible `ERROR` trace to the Docker logs if the network request fails or times out.

**Example:**
The detector tries to send an alert to `YOUR/WEBHOOK/URL`. `requests` throws a `MissingSchema` exception. The script catches it and prints `ERROR - Slack alert FAILED for 192.168.1.5: Invalid URL` to the terminal, immediately exposing the configuration issue.

### 3. `detector/blocker.py` (The Sudo & Logging Fix)
This module was updated to execute firewall drops natively and log its progress.

**What was there before:**
```python
        try:
            subprocess.run(['sudo', 'iptables', '-I', 'DOCKER-USER', '-s', ip, '-j', 'DROP'], check=True)
            self.banned_ips.add(ip)
        except Exception as e:
            logging.error(f"Failed to ban IP {ip}: {e}")
```

**What it was changed to:**
```python
        try:
            subprocess.run(['iptables', '-I', 'DOCKER-USER', '-s', ip, '-j', 'DROP'], check=True)
            self.banned_ips.add(ip)
            logging.info(f'BANNED IP {ip} for {duration}s')
        except Exception as e:
            logging.error(f'Failed to ban IP {ip}: {e}')
```

**What happens:**
Inside the Docker container, the daemon is already running as the `root` user. Prefixing the command with `sudo` is not only redundant but can cause execution paths to fail depending on the slim OS environment variables. We stripped `sudo` from both the `ban_ip` and `unban_ip_manually` functions. 
Furthermore, we wrapped the `_write_audit` function in a `try/except` block to ensure that if a disk write fails, the entire application doesn't crash, and the error is printed directly to the Docker logs.

**Example:**
The `ban_ip` function receives `192.168.1.5`. It executes `iptables -I DOCKER-USER...` natively as root. It successfully adds the rule to the host firewall. It then prints `INFO - BANNED IP 192.168.1.5 for 600s` to the logs, giving us visual confirmation that the muscle of the application is working.

---

## Summary of the Complete Lifecycle Flow

1. **`main.py`** boots the daemon, now equipped with comprehensive visibility via the `logging` module.
2. **`detector.py`** detects an anomaly and passes the IP to the Blocker.
3. **`blocker.py`** executes `iptables` directly as root (without sudo) and logs a highly visible `INFO` success message.
4. **`blocker.py`** attempts to write the Audit Log to `/app/detector-audit.log`, bypassing the Read-Only volume restrictions, and safely logs if a disk error occurs.
5. **`notifier.py`** executes the POST request to Slack. If the URL is a dummy placeholder, it prints a loud error exposing the issue. If the URL is correct, it prints `status=200 response=ok`.
