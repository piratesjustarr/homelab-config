#!/usr/bin/env python3
"""
Huginn Executor (Ops Agent)

Handles system operations, monitoring, power management, DNS.
Runs on: huginn.nessie-hippocampus.ts.net:5000
"""

import sys
sys.path.insert(0, '/var/home/matt/homelab-config')

from agents.base_agent import AgentExecutor
import logging

logger = logging.getLogger(__name__)


class HuginnExecutor(AgentExecutor):
    """Ops agent for system operations, monitoring, power management"""
    
    EXECUTOR_NAME = "huginn-executor"
    EXECUTOR_VERSION = "0.1.0"
    
    def register_handlers(self):
        """Register task handlers for Huginn"""
        
        self.task_handlers = {
            'ops-health-check': self.handle_health_check,
            'power-wake': self.handle_wake_on_lan,
            'power-status': self.handle_power_status,
            'monitor-pihole': self.handle_monitor_pihole,
            'monitor-plex': self.handle_monitor_plex,
            'network-check': self.handle_network_check,
        }
    
    def handle_health_check(self, params):
        """Verify Huginn is operational"""
        result = self.run_command('uptime && free -h')
        return {
            'output': f"Huginn health check:\n{result['output']}"
        }
    
    def handle_wake_on_lan(self, params):
        """Send WoL magic packet to wake a machine"""
        mac_address = params.get('mac_address')
        
        if not mac_address:
            return {'output': 'Error: mac_address required', 'success': False}
        
        # Use etherwake if available
        cmd = f"etherwake {mac_address} 2>/dev/null || echo 'Waking {mac_address}...'"
        result = self.run_command(cmd, timeout=10)
        
        return {
            'output': result['output'],
            'success': True  # WoL doesn't have reliable feedback
        }
    
    def handle_power_status(self, params):
        """Check power status of machines"""
        machines = ['surtr', 'fenrir', 'skadi']
        
        status = {}
        for machine in machines:
            cmd = f"ping -c 1 -W 1 {machine}.nessie-hippocampus.ts.net >/dev/null 2>&1 && echo 'online' || echo 'offline'"
            result = self.run_command(cmd, timeout=5)
            status[machine] = result['output'].strip()
        
        output = '\n'.join([f"{k}: {v}" for k, v in status.items()])
        return {
            'output': output,
            'success': True
        }
    
    def handle_monitor_pihole(self, params):
        """Check Pi-hole DNS health"""
        cmd = "curl -s http://localhost/admin/api.php?summary 2>/dev/null | jq . || echo 'Pi-hole API unavailable'"
        result = self.run_command(cmd, timeout=10)
        
        return {
            'output': result['output'],
            'success': result['success']
        }
    
    def handle_monitor_plex(self, params):
        """Check Plex server status"""
        # Assuming Plex runs on Muninn (Odroid)
        cmd = "curl -s http://muninn.nessie-hippocampus.ts.net:32400/status/sessions | xmllint --format - 2>/dev/null || echo 'Plex unavailable'"
        result = self.run_command(cmd, timeout=10)
        
        return {
            'output': result['output'],
            'success': result['success']
        }
    
    def handle_network_check(self, params):
        """Verify network connectivity across Yggdrasil"""
        machines = ['fenrir', 'jormungandr', 'surtr', 'muninn']
        
        checks = []
        for machine in machines:
            cmd = f"ping -c 1 -W 1 {machine}.nessie-hippocampus.ts.net >/dev/null 2>&1 && echo '{machine}: OK' || echo '{machine}: FAIL'"
            result = self.run_command(cmd, timeout=5)
            checks.append(result['output'].strip())
        
        output = '\n'.join(checks)
        return {
            'output': output,
            'success': True
        }


if __name__ == '__main__':
    agent = HuginnExecutor()
    agent.run(host='0.0.0.0', port=5000, debug=False)
