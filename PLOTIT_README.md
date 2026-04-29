# Plotit: Terminal Graphing Utility

`plotit.py` is a simple Python utility designed to extract baseline metrics from the Anomaly Detection Daemon's audit log and visualize them directly in the terminal as an ASCII/TUI line chart.

## Prerequisites

The script requires the `plotext` library.
```bash
sudo apt-get install -y python3-pip
sudo pip3 install plotext --break-system-packages
```

## Usage

You can run the script with Python 3. It will automatically fetch the logs from the running Docker container (`hng-13-stage-03-detector-1`) and plot the effective mean.

```bash
# Plot the last 24 hours (default)
sudo python3 plotit.py

# Plot the last 6 hours
sudo python3 plotit.py -t 6

# Plot the last 3 hours
sudo python3 plotit.py -t 3
```

## Example Output

```text
--- Baseline Effective Mean (Last 3 Hours) ---
...
   19:00    21:49 21:50  21:52 21:53 21:54 21:55    21:57   21:59 22:00 22:01   
Requests / second                    Time (UTC)   
```
