import subprocess
import time
import logging

class Blocker:
    def __init__(self, unbanner, audit_log_path="/var/log/nginx/detector-audit.log"):
        self.unbanner = unbanner
        self.banned_ips = set()
        self.audit_log_path = audit_log_path
        
    def is_banned(self, ip):
        """Checks if an IP is currently banned."""
        return ip in self.banned_ips
        
    def ban_ip(self, ip, condition, rate, baseline):
        """Bans an IP using iptables and logs it to the audit log."""
        if self.is_banned(ip):
            return 0
            
        # 1. Ask the Unbanner how long the ban should last (Backoff Schedule)
        duration = self.unbanner.get_ban_duration(ip)
        
        # 2. Execute iptables DROP rule on host system targeting DOCKER-USER
        try:
            # Note: Requires sudo permissions without password prompts for the daemon user
            subprocess.run(['sudo', 'iptables', '-I', 'DOCKER-USER', '-s', ip, '-j', 'DROP'], check=True)
            self.banned_ips.add(ip)
        except Exception as e:
            logging.error(f"Failed to ban IP {ip}: {e}")
            return 0
            
        # 3. Tell the Unbanner to schedule a removal for later
        if duration != -1: # -1 means permanent
            self.unbanner.schedule_unban(ip, duration, self)
            
        # 4. Write exactly formatted Audit Log
        self._write_audit("BAN", ip, condition, rate, baseline, duration)
        
        return duration
        
    def _write_audit(self, action, ip, condition, rate, baseline, duration):
        """Writes structured log entries to the audit log."""
        timestamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        # Format: [timestamp] ACTION ip | condition | rate | baseline | duration
        log_line = f"[{timestamp}] {action} {ip} | {condition} | {rate} | {baseline:.2f} | {duration}\n"
        with open(self.audit_log_path, 'a') as f:
            f.write(log_line)
            
    def unban_ip_manually(self, ip):
        """Called automatically by unbanner.py when schedule expires."""
        if ip in self.banned_ips:
            try:
                subprocess.run(['sudo', 'iptables', '-D', 'DOCKER-USER', '-s', ip, '-j', 'DROP'], check=True)
                self.banned_ips.remove(ip)
                self._write_audit("UNBAN", ip, "Schedule Expired", 0, 0, 0)
                return True
            except Exception as e:
                logging.error(f"Failed to unban IP {ip}: {e}")
        return False
