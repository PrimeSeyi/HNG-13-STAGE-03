#!/bin/bash

# Prompt for username and IP address
read -p "Enter server username: " USERNAME
read -p "Enter server IP address: " IP_ADDRESS

echo "Connecting to $USERNAME@$IP_ADDRESS to provision the server..."

# Ensure target directory exists on the remote host
ssh -o StrictHostKeyChecking=accept-new "$USERNAME@$IP_ADDRESS" "mkdir -p ~/nextcloud-deployment/nginx ~/nextcloud-deployment/detector"

echo "Copying all configuration and daemon files to the server..."
# SCP the files we built locally to the remote host
scp -r ./nginx/nginx.conf "$USERNAME@$IP_ADDRESS:~/nextcloud-deployment/nginx/"
scp -r ./detector/* "$USERNAME@$IP_ADDRESS:~/nextcloud-deployment/detector/"
scp docker-compose.yml "$USERNAME@$IP_ADDRESS:~/nextcloud-deployment/"

echo "Executing Docker setup remotely..."
# SSH command to execute the provisioning script remotely
ssh -o StrictHostKeyChecking=accept-new "$USERNAME@$IP_ADDRESS" << 'EOF'

# Exit on any error
set -e

echo "Updating packages..."
sudo apt-get update -y

echo "Installing Docker & Docker Compose if not present..."
if ! command -v docker &> /dev/null; then
    sudo apt-get install -y ca-certificates curl gnupg
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update -y
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
else
    echo "Docker is already installed."
fi

# Ensure user is in the docker group to run docker commands without sudo
sudo usermod -aG docker $USER || true

cd ~/nextcloud-deployment

echo "Building and Starting Docker Compose stack..."
sudo docker compose up --build -d

echo "Provisioning complete!"
echo "Nextcloud is accessible via the server's IP address."
echo "Live Metrics Dashboard is accessible via your Domain."
EOF
