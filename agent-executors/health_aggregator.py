"""
Health Status Aggregator Module

Queries all executor health endpoints and aggregates results into a unified status response.
"""

import requests
from typing import Dict, List, Any
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class HealthAggregator:
    """Aggregates health status from all running agents"""
    
    def __init__(self, executors: Dict[str, str]):
        """
        Initialize with executor locations.
        
        Args:
            executors: Dict mapping executor name to URL (e.g., {"code-agent": "surtr:5001"})
        """
        self.executors = executors
        self.timeout = 5
    
    def query_all(self) -> Dict[str, Any]:
        """Query all executor health endpoints and aggregate results"""
        components = {}
        healthy_count = 0
        
        for name, url in self.executors.items():
            try:
                response = requests.get(
                    f"http://{url}/health",
                    timeout=self.timeout
                )
                if response.ok:
                    health = response.json()
                    health['url'] = url
                    components[name] = health
                    if health.get('status') == 'healthy':
                        healthy_count += 1
                else:
                    components[name] = {
                        'status': 'unhealthy',
                        'error': f'HTTP {response.status_code}',
                        'url': url
                    }
            except Exception as e:
                components[name] = {
                    'status': 'unreachable',
                    'error': str(e),
                    'url': url
                }
        
        return {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'healthy': healthy_count == len(self.executors),
            'health_count': f'{healthy_count}/{len(self.executors)}',
            'components': components
        }


# Example usage
if __name__ == '__main__':
    executors = {
        'coordinator': 'jormungandr:5000',
        'code-agent': 'surtr:5001',
        'fenrir-executor': 'fenrir.nessie-hippocampus.ts.net:5000',
    }
    
    agg = HealthAggregator(executors)
    status = agg.query_all()
    
    import json
    print(json.dumps(status, indent=2))
