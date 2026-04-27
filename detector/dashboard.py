from flask import Flask, jsonify, render_template_string
import psutil
import time
import operator

class Dashboard:
    def __init__(self, monitor, baseline_calc, blocker, config):
        self.monitor = monitor
        self.baseline_calc = baseline_calc
        self.blocker = blocker
        self.host = config['dashboard']['host']
        self.port = config['dashboard']['port']
        self.start_time = time.time()
        
        self.app = Flask(__name__)
        
        # Route definitions
        self.app.add_url_rule('/api/metrics', 'metrics', self.metrics)
        self.app.add_url_rule('/', 'index', self.index)
        
    def get_uptime(self):
        """Calculates uptime in a human-readable format."""
        diff = int(time.time() - self.start_time)
        hours, remainder = divmod(diff, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours}h {minutes}m {seconds}s"
        
    def metrics(self):
        """Returns JSON payload with all required system metrics."""
        global_rate, ip_rates, _ = self.monitor.get_current_rates()
        mean, stddev, _ = self.baseline_calc.get_baselines()
        
        # Sort IP dictionary by rate (descending) and grab top 10
        sorted_ips = sorted(ip_rates.items(), key=operator.itemgetter(1), reverse=True)
        top_10 = [{"ip": ip, "rate": rate} for ip, rate in sorted_ips[:10]]
        
        banned = list(self.blocker.banned_ips)
        cpu = psutil.cpu_percent()
        mem = psutil.virtual_memory().percent
        
        payload = {
            "banned_ips": banned,
            "global_req_s": global_rate,
            "top_ips": top_10,
            "cpu_usage": cpu,
            "memory_usage": mem,
            "mean": round(mean, 2),
            "stddev": round(stddev, 2),
            "uptime": self.get_uptime()
        }
        return jsonify(payload)
        
    def index(self):
        """Serves the frontend HTML."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Live Metrics Dashboard</title>
            <style>
                body { font-family: Arial, sans-serif; background: #121212; color: #fff; padding: 20px; }
                .card { background: #1e1e1e; padding: 15px; border-radius: 8px; margin-bottom: 20px; border: 1px solid #333; }
                h2 { margin-top: 0; color: #bb86fc; font-size: 1.2rem; }
                table { width: 100%; border-collapse: collapse; }
                th, td { padding: 8px; text-align: left; border-bottom: 1px solid #333; }
                th { color: #03dac6; }
                .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
                .banned { color: #cf6679; font-weight: bold; }
                .val { font-size: 1.5rem; font-weight: bold; color: #fff; }
            </style>
        </head>
        <body>
            <h1 style="color: #03dac6;">Daemon Live Metrics</h1>
            <div class="grid">
                <div class="card">
                    <h2>System Status</h2>
                    <p>Uptime: <span id="uptime" class="val"></span></p>
                    <p>CPU Usage: <span id="cpu" class="val"></span>%</p>
                    <p>Memory Usage: <span id="mem" class="val"></span>%</p>
                </div>
                <div class="card">
                    <h2>Traffic Baselines</h2>
                    <p>Global Requests (Last 60s): <span id="global" class="val"></span></p>
                    <p>Effective Mean: <span id="mean" class="val"></span> req/s</p>
                    <p>Effective StdDev: <span id="stddev" class="val"></span></p>
                </div>
            </div>
            
            <div class="card">
                <h2>Banned IPs</h2>
                <ul id="banned_list" class="banned"></ul>
            </div>
            
            <div class="card">
                <h2>Top 10 Source IPs (Last 60s)</h2>
                <table>
                    <thead><tr><th>IP Address</th><th>Requests</th></tr></thead>
                    <tbody id="top_ips_table"></tbody>
                </table>
            </div>

            <script>
                function fetchMetrics() {
                    fetch('/api/metrics')
                        .then(r => r.json())
                        .then(data => {
                            document.getElementById('uptime').innerText = data.uptime;
                            document.getElementById('cpu').innerText = data.cpu_usage;
                            document.getElementById('mem').innerText = data.memory_usage;
                            document.getElementById('global').innerText = data.global_req_s;
                            document.getElementById('mean').innerText = data.mean;
                            document.getElementById('stddev').innerText = data.stddev;
                            
                            const bannedUl = document.getElementById('banned_list');
                            bannedUl.innerHTML = '';
                            if (data.banned_ips.length === 0) {
                                bannedUl.innerHTML = '<li style="color: #aaa; font-weight: normal;">No active bans</li>';
                            } else {
                                data.banned_ips.forEach(ip => {
                                    let li = document.createElement('li');
                                    li.innerText = ip;
                                    bannedUl.appendChild(li);
                                });
                            }
                            
                            const topTable = document.getElementById('top_ips_table');
                            topTable.innerHTML = '';
                            data.top_ips.forEach(item => {
                                let tr = document.createElement('tr');
                                tr.innerHTML = `<td>${item.ip}</td><td><span class="val" style="font-size: 1rem;">${item.rate}</span></td>`;
                                topTable.appendChild(tr);
                            });
                        })
                        .catch(err => console.error(err));
                }
                
                // Fetch every 2 seconds to satisfy the "< 3 seconds" requirement
                setInterval(fetchMetrics, 2000);
                fetchMetrics(); 
            </script>
        </body>
        </html>
        """
        return render_template_string(html)
        
    def start(self):
        """Runs the Flask server, blocking the main thread."""
        self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False)
