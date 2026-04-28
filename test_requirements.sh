#!/bin/bash
echo "=== 1. RUNNING CONTAINERS ==="
sudo docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo ""
echo "=== 2. NGINX ACCESS LOG (last 3 lines) ==="
sudo docker exec hng-13-stage-03-nginx-1 tail -3 /var/log/nginx/hng-access.log 2>/dev/null || echo "FAIL: cannot read log"

echo ""
echo "=== 3. NGINX CONF - X-Forwarded-For / log_format / real_ip ==="
sudo docker exec hng-13-stage-03-nginx-1 cat /etc/nginx/nginx.conf | grep -i -E "real_ip|x-forwarded|log_format|access_log"

echo ""
echo "=== 4. SHARED VOLUME MOUNTS - detector container ==="
sudo docker inspect hng-13-stage-03-detector-1 --format '{{range .Mounts}}{{.Source}} -> {{.Destination}} mode={{.Mode}}{{"\n"}}{{end}}'

echo ""
echo "=== 5. METRICS API RESPONSE ==="
curl -s http://localhost:5000/api/metrics

echo ""
echo "=== 6. IPTABLES DOCKER-USER CHAIN ==="
sudo iptables -L DOCKER-USER -n

echo ""
echo "=== 7. AUDIT LOG ==="
sudo docker exec hng-13-stage-03-detector-1 cat /app/detector-audit.log 2>/dev/null || echo "NO AUDIT LOG YET"

echo ""
echo "=== 8. DETECTOR LOGS (last 20 lines) ==="
sudo docker logs hng-13-stage-03-detector-1 --tail 20 2>&1

echo ""
echo "=== 9. HTTP ACCESS TEST - server IP ==="
curl -s -o /dev/null -w "HTTP Status: %{http_code}" http://20.169.136.102/

echo ""
echo "=== 10. NEXTCLOUD REACHABLE VIA IP ==="
curl -s -o /dev/null -w "HTTP Status: %{http_code}" http://20.169.136.102/login

echo ""
echo "=== 11. DASHBOARD REACHABLE ON PORT 5000 ==="
curl -s -o /dev/null -w "HTTP Status: %{http_code}" http://localhost:5000/

echo ""
echo "=== 12. VOLUME NAME CHECK ==="
sudo docker volume ls | grep -i hng
