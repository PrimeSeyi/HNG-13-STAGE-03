import argparse
import subprocess
import datetime
import re
import sys
import plotext as plt

def get_logs():
    cmd = ["sudo", "docker", "exec", "hng-13-stage-03-detector-1", "cat", "/app/detector-audit.log"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("Error fetching logs from container.")
        sys.exit(1)
    return result.stdout.splitlines()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TUI Graph for Detector Baseline")
    parser.add_argument('-t', '--hours', type=int, default=24, help="Time period in hours to graph")
    args = parser.parse_args()
    
    lines = get_logs()
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=args.hours)
    
    times = []
    values = []
    
    for line in lines:
        if "BASELINE GLOBAL" in line:
            parts = line.split(" | ")
            if len(parts) >= 4:
                ts_match = re.search(r'\[(.*?)Z\]', parts[0])
                if ts_match:
                    ts_str = ts_match.group(1)
                    # Example ts_str: 2026-04-29T20:00:00
                    ts = datetime.datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S")
                    if ts >= cutoff:
                        val = float(parts[3])
                        # Keep only the HH:MM for clean x-axis
                        times.append(ts_str.split('T')[1][:5]) 
                        values.append(val)
                        
    if not values:
        print(f"No baseline data found in the last {args.hours} hours.")
        sys.exit(0)
        
    plt.clear_figure()
    x_indices = list(range(len(values)))
    plt.plot(x_indices, values, marker="dot", color="cyan")
    plt.xticks(x_indices, times)
    plt.title(f"Baseline Effective Mean (Last {args.hours} Hours)")
    plt.xlabel("Time (UTC)")
    plt.ylabel("Requests / second")
    plt.theme("dark")
    plt.plotsize(100, 20)
    plt.show()
