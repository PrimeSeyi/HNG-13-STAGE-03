FROM python:3.10-slim

# Install iptables, sudo, and procps (for psutil)
RUN apt-get update && apt-get install -y \
    iptables \
    sudo \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy daemon scripts
COPY . .

# Run the daemon
CMD ["python", "main.py"]
