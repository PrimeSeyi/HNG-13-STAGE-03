#!/bin/bash
echo "=== NEXTCLOUD via direct IP ==="
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://20.169.136.102/

echo ""
echo "=== NEXTCLOUD homepage contains 'Nextcloud' word ==="
curl -s http://20.169.136.102/ | grep -ic "nextcloud" && echo "PASS: Nextcloud word found" || echo "FAIL: Nextcloud word not found"

echo ""
echo "=== DASHBOARD HTML title ==="
curl -s http://localhost:5000/ | grep -i "<title>"

echo ""
echo "=== NGINX CONFIG ==="
sudo docker exec hng-13-stage-03-nginx-1 cat /etc/nginx/nginx.conf

echo ""
echo "=== HNG-nginx-logs volume name (exact) ==="
sudo docker volume ls | grep HNG-nginx-logs

echo ""
echo "=== DETECTOR reads the correct log path ==="
sudo docker exec hng-13-stage-03-detector-1 grep log_file config.yaml

echo ""
echo "=== REAL INTERNET TRAFFIC - recent source IPs ==="
sudo docker exec hng-13-stage-03-nginx-1 tail -10 /var/log/nginx/hng-access.log | python3 -c "import sys,json; [print(json.loads(l)['source_ip'], json.loads(l)['status']) for l in sys.stdin if l.strip()]"
