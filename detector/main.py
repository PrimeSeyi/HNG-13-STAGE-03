import yaml
import logging
import os
import sys

# Ensure Python can import from the current directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from monitor import LogMonitor
from baseline import BaselineCalculator
from unbanner import Unbanner
from blocker import Blocker
from notifier import Notifier
from detector import AnomalyDetector
from dashboard import Dashboard

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def main():
    logging.info("Starting Anomaly Detection Daemon...")
    
    # 1. Load Configurations
    config_path = "config.yaml"
    if not os.path.exists(config_path):
        config_path = "detector/config.yaml"
        
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    # 2. Initialize Core Components
    monitor = LogMonitor(log_file=config['app']['log_file'], window_size=config['app']['window_size_seconds'])
    baseline_calc = BaselineCalculator(
        monitor=monitor, 
        history_minutes=config['app']['baseline_history_minutes'],
        audit_log_path=config['app']['audit_log']
    )
    
    notifier = Notifier(webhook_url=config['slack']['webhook_url'])
    unbanner = Unbanner(backoff_schedule=config['backoff_schedule'], notifier=notifier)
    blocker = Blocker(unbanner=unbanner, audit_log_path=config['app']['audit_log'])
    
    detector = AnomalyDetector(
        monitor=monitor, 
        baseline_calc=baseline_calc, 
        blocker=blocker, 
        notifier=notifier, 
        thresholds=config['thresholds']
    )
    
    dashboard = Dashboard(
        monitor=monitor,
        baseline_calc=baseline_calc,
        blocker=blocker,
        config=config
    )
    
    # 3. Start Background Threads
    logging.info("Starting background processes...")
    monitor.start()
    baseline_calc.start()
    unbanner.start()
    detector.start()
    
    # 4. Start the Web UI (This will block the main thread and keep the application alive)
    logging.info(f"Starting Dashboard on {config['dashboard']['host']}:{config['dashboard']['port']}")
    dashboard.start()

if __name__ == "__main__":
    main()
