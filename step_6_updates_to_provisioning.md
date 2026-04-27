# Step 6: Updates to Provisioning (Comprehensive Deep Dive & Flow)

This document provides a highly elaborate, exhaustive breakdown of every single change made to the deployment scripts. It shows exactly what was there before, what it was changed to, and why. No logic is skipped or summarized.

---

## The Big Picture: How is it called?

The `provision.sh` script is the main entry point for the deployment. You run it from your local machine, and it automatically connects to your Linux server, uploads our new Python code, and starts the Docker environment.

```bash
# Execute locally
bash provision.sh
# Prompts for username and IP, then automates everything via SSH and SCP
```

---

## Function-by-Function Flow with Sample Data

### 1. `docker-compose.yml` (The Container Architecture)
This file defines how the containers are networked and built.

**What was there before:**
```yaml
# OLD DOCKER COMPOSE SNIPPET
  detector:
    # A lightweight dummy container representing "your detector"
    image: alpine:latest
    restart: always
    command: sh -c "tail -f /var/log/nginx/hng-access.log"
    volumes:
      - HNG-nginx-logs:/var/log/nginx:ro
```

**What it was changed to:**
```yaml
# NEW DOCKER COMPOSE SNIPPET
  detector:
    build: ./detector
    restart: always
    network_mode: "host"  # Required so iptables rules affect the host machine's firewall
    cap_add:
      - NET_ADMIN         # Required permission to execute iptables modifications
    volumes:
      - HNG-nginx-logs:/var/log/nginx:ro  # Read-only mount of Nginx JSON logs
    user: root 
```

**What happens:**
Instead of pulling a pre-built `alpine` image, Docker is now instructed to `build: ./detector`. It will look inside the `detector` folder, find our new `Dockerfile`, and compile all our Python scripts into a container. 
Critically, we added `network_mode: "host"` and `cap_add: [NET_ADMIN]`. Without these two lines, Docker creates a completely isolated networking bubble. If our Python script ran `iptables` inside a normal container, it would only block traffic *inside* that useless bubble, not the actual server! By using `network_mode: host`, the container is merged with the Linux host's physical network adapters, allowing our `blocker.py` script to physically cut off attacking IPs at the server boundary.

**Example:**
When `docker compose up` is executed, it compiles `main.py`, `monitor.py`, etc., into an image. It starts the container. The container binds port `5000` directly to the host machine.

### 2. `blocker.py` (The Firewall Chain Modification)
This script was updated to ensure Docker respects the firewall blocks.

**What was there before:**
```python
subprocess.run(['sudo', 'iptables', '-A', 'INPUT', '-s', ip, '-j', 'DROP'], check=True)
subprocess.run(['sudo', 'iptables', '-D', 'INPUT', '-s', ip, '-j', 'DROP'], check=True)
```

**What it was changed to:**
```python
subprocess.run(['sudo', 'iptables', '-I', 'DOCKER-USER', '-s', ip, '-j', 'DROP'], check=True)
subprocess.run(['sudo', 'iptables', '-D', 'DOCKER-USER', '-s', ip, '-j', 'DROP'], check=True)
```

**What happens:**
Docker operates a complex firewall routing table. If we drop traffic on the `INPUT` chain, Docker's `PREROUTING` chain intercepts the traffic *first* and routes it to Nginx anyway, bypassing our ban entirely! By changing the target chain from `INPUT` to `DOCKER-USER` using `-I` (Insert), we inject our drop rules into the exact stage of the firewall that Docker promises to respect *before* it forwards traffic to Nginx or Nextcloud.

**Example:**
IP `192.168.1.5` attacks. `blocker.py` executes `iptables -I DOCKER-USER -s 192.168.1.5 -j DROP`. Docker's internal router checks the `DOCKER-USER` chain, sees the drop rule, and instantly kills the connection before Nginx even knows it exists.

### 3. `nginx/nginx.conf` (The Domain Router)
This configuration was updated to route traffic cleanly between Nextcloud and the Dashboard.

**What was there before:**
```nginx
    server {
        listen 80;
        location / {
            proxy_pass http://nextcloud:80;
        }
    }
```

**What it was changed to:**
```nginx
    # 1. Default Server: IP-only traffic routes to Nextcloud
    server {
        listen 80 default_server;
        location / { proxy_pass http://nextcloud:80; }
    }

    # 2. Domain Server: Domain traffic routes to the Python Dashboard
    server {
        listen 80;
        server_name ~^(?!^[0-9.]+$).*$; 
        location / { proxy_pass http://172.17.0.1:5000; }
    }
```

**What happens:**
Your instructions required the Dashboard to be served via a Domain, and Nextcloud to be served via IP address. We added a `server_name` Regex rule: `~^(?!^[0-9.]+$).*$`. This mathematical regex matches any HTTP request whose "Host" header contains letters (a domain). If a domain is used, Nginx routes the traffic to `172.17.0.1:5000` (which is the Docker gateway IP leading to our `network_mode: host` Python daemon). If an IP address is typed in the browser, the regex fails, and it falls back to the `default_server` block, routing to Nextcloud.

**Example:**
You type `192.168.1.100` in the browser. Nginx routes you to Nextcloud. You type `metrics.yourdomain.com` in the browser. Nginx routes you to the Python Flask dashboard.

### 4. `provision.sh` (The Bootstrapper)
This file was rewritten to handle remote code uploading.

**What was there before:**
```bash
ssh -o StrictHostKeyChecking=accept-new "$USERNAME@$IP_ADDRESS" << 'EOF'
# Inline cat of nginx.conf
# Inline cat of docker-compose.yml
sudo docker compose up -d
EOF
```

**What it was changed to:**
```bash
# Locally copy all Python files to the remote server FIRST
scp -r ./nginx/nginx.conf "$USERNAME@$IP_ADDRESS:~/nextcloud-deployment/nginx/"
scp -r ./detector/* "$USERNAME@$IP_ADDRESS:~/nextcloud-deployment/detector/"
scp docker-compose.yml "$USERNAME@$IP_ADDRESS:~/nextcloud-deployment/"

# Then SSH in and build them
ssh -o StrictHostKeyChecking=accept-new "$USERNAME@$IP_ADDRESS" << 'EOF'
sudo docker compose up --build -d
EOF
```

**What happens:**
Instead of trying to "type" all 15 Python files out remotely using `cat << EOF` loops, the script now uses `scp` (Secure Copy Protocol). It physically copies the entire `detector` folder, the `nginx.conf`, and the `docker-compose.yml` from your Windows machine up to the Linux server. Once the files are successfully transferred, it logs in via SSH and executes `docker compose up --build -d`.

**Example:**
You run `bash provision.sh`. It asks for `ubuntu` and `1.2.3.4`. It silently copies `main.py`, `dashboard.py`, `Dockerfile`, etc., to `~/nextcloud-deployment/detector` on the remote server. It then installs Docker and compiles the Python app.

---

## Summary of the Complete Lifecycle Flow

1. **`provision.sh`** asks the user for server credentials.
2. **`provision.sh`** uses `scp` to copy the local `detector/` codebase and Docker files to the remote server.
3. **`provision.sh`** logs into the remote server via SSH and executes `docker compose up --build -d`.
4. Concurrently, Docker reads the `docker-compose.yml`, builds the custom Python image, and launches the daemon container with `NET_ADMIN` and `network_mode: host` privileges.
5. Finally, Nginx boots up. When a user visits via Domain, Nginx proxies to the Dashboard on port 5000. When they visit via IP, it proxies to Nextcloud on port 80.
