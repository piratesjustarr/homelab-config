#!/usr/bin/env python3
"""
LLM Router - Health check and capability-based routing

Loads llm_hosts.yaml, checks availability, routes by task capability.
"""

import os
import json
import yaml
import logging
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class LLMHost:
    """Represents an LLM endpoint"""
    name: str
    url: str
    model: str
    capabilities: List[str]
    priority: int = 1
    healthy: bool = False
    last_check: float = 0
    
    @property
    def api_base(self) -> str:
        return self.url
    
    @property 
    def litellm_model(self) -> str:
        """Model name for litellm (openai provider for ramalama)"""
        return f"openai/{self.model}"


@dataclass  
class CloudProvider:
    """Cloud LLM provider (fallback)"""
    name: str
    model: str
    capabilities: List[str]
    priority: int = 99
    
    @property
    def litellm_model(self) -> str:
        if self.name == 'anthropic':
            return f"anthropic/{self.model}"
        return self.model


class LLMRouter:
    """
    Routes LLM requests based on capability and availability.
    
    Usage:
        router = LLMRouter()
        router.load_config()
        router.health_check()
        
        host = router.get_host_for_task('code-generation')
        # Use host.api_base and host.litellm_model
    """
    
    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = Path(__file__).parent / 'llm_hosts.yaml'
        self.config_path = Path(config_path)
        
        self.hosts: List[LLMHost] = []
        self.cloud_providers: List[CloudProvider] = []
        self.routing: Dict[str, List[str]] = {}
        
    def load_config(self) -> bool:
        """Load configuration from YAML file"""
        if not self.config_path.exists():
            logger.error(f"Config not found: {self.config_path}")
            return False
        
        try:
            with open(self.config_path) as f:
                config = yaml.safe_load(f)
            
            # Load hosts
            for h in config.get('hosts', []):
                self.hosts.append(LLMHost(
                    name=h['name'],
                    url=h['url'],
                    model=h['model'],
                    capabilities=h.get('capabilities', []),
                    priority=h.get('priority', 1),
                ))
            
            # Load cloud providers
            for c in config.get('cloud', []):
                self.cloud_providers.append(CloudProvider(
                    name=c['name'],
                    model=c['model'],
                    capabilities=c.get('capabilities', []),
                    priority=c.get('priority', 99),
                ))
            
            # Load routing
            self.routing = config.get('routing', {})
            
            logger.info(f"Loaded {len(self.hosts)} hosts, {len(self.cloud_providers)} cloud providers")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return False
    
    def check_host(self, host: LLMHost, timeout: int = 5) -> bool:
        """Check if a host is healthy"""
        try:
            url = f"{host.url}/models"
            req = urllib.request.Request(url, headers={'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    host.healthy = True
                    logger.debug(f"Host {host.name} is healthy")
                    return True
        except Exception as e:
            logger.debug(f"Host {host.name} unhealthy: {e}")
        
        host.healthy = False
        return False
    
    def health_check(self, timeout: int = 5) -> Dict[str, bool]:
        """Check all hosts and return health status"""
        import time
        
        results = {}
        for host in self.hosts:
            results[host.name] = self.check_host(host, timeout)
            host.last_check = time.time()
        
        healthy_count = sum(1 for h in self.hosts if h.healthy)
        logger.info(f"Health check: {healthy_count}/{len(self.hosts)} hosts healthy")
        
        return results
    
    def get_hosts_by_capability(self, capability: str) -> List[LLMHost]:
        """Get all healthy hosts that have a capability"""
        return [
            h for h in self.hosts 
            if h.healthy and capability in h.capabilities
        ]
    
    def get_host_for_task(self, task_type: str) -> Optional[LLMHost]:
        """
        Get best host for a task type.
        
        Uses routing config to map task_type -> capabilities,
        then finds healthy host with matching capability.
        """
        # Get required capabilities for this task type
        capabilities = self.routing.get(task_type, self.routing.get('default', []))
        
        # Find healthy hosts with matching capabilities
        for cap in capabilities:
            hosts = self.get_hosts_by_capability(cap)
            if hosts:
                # Sort by priority (lower = better)
                hosts.sort(key=lambda h: h.priority)
                return hosts[0]
        
        # No local host available, return None (caller should use cloud)
        return None
    
    def get_cloud_fallback(self, task_type: str = None) -> Optional[CloudProvider]:
        """Get cloud provider for fallback"""
        if not self.cloud_providers:
            return None
        
        # Check if API key is available
        if not os.environ.get('ANTHROPIC_API_KEY'):
            # Try to load from crush config
            try:
                config_path = Path.home() / '.local/share/crush/crush.json'
                if config_path.exists():
                    with open(config_path) as f:
                        config = json.load(f)
                        key = config.get('providers', {}).get('anthropic', {}).get('api_key')
                        if key:
                            os.environ['ANTHROPIC_API_KEY'] = key
            except Exception:
                pass
        
        if not os.environ.get('ANTHROPIC_API_KEY'):
            logger.warning("No Anthropic API key available for cloud fallback")
            return None
        
        # Return first cloud provider (sorted by priority)
        return sorted(self.cloud_providers, key=lambda c: c.priority)[0]
    
    def get_litellm_model_list(self) -> List[Dict[str, Any]]:
        """
        Generate litellm Router model_list config.
        
        Returns list suitable for litellm.Router(model_list=...)
        """
        model_list = []
        
        # Add healthy local hosts
        for host in self.hosts:
            if host.healthy:
                model_list.append({
                    "model_name": host.capabilities[0] if host.capabilities else "general",
                    "litellm_params": {
                        "model": host.litellm_model,
                        "api_base": host.api_base,
                        "api_key": "local",  # ramalama doesn't validate
                    }
                })
        
        # Add cloud fallback
        cloud = self.get_cloud_fallback()
        if cloud:
            model_list.append({
                "model_name": "fallback",
                "litellm_params": {
                    "model": cloud.litellm_model,
                }
            })
        
        return model_list


def check_llm_health() -> Dict[str, Dict[str, Any]]:
    """
    Convenience function for CLI status command.
    Returns health status of all configured LLMs.
    """
    router = LLMRouter()
    router.load_config()
    
    results = {}
    for host in router.hosts:
        healthy = router.check_host(host)
        results[host.name] = {
            'healthy': healthy,
            'status': 'online' if healthy else 'offline',
            'model': host.model,
            'url': host.url,
        }
    
    # Check cloud
    cloud = router.get_cloud_fallback()
    if cloud:
        results['cloud-anthropic'] = {
            'healthy': True,
            'status': 'available',
            'model': cloud.model,
        }
    else:
        results['cloud-anthropic'] = {
            'healthy': False,
            'status': 'no API key',
            'model': 'claude-sonnet',
        }
    
    return results


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    router = LLMRouter()
    router.load_config()
    
    print("=== LLM Health Check ===\n")
    
    health = router.health_check()
    for host in router.hosts:
        status = "✓" if host.healthy else "✗"
        print(f"{status} {host.name}: {host.model} @ {host.url}")
    
    print("\n=== Routing Test ===\n")
    
    for task_type in ['code-generation', 'text-processing', 'reasoning', 'general']:
        host = router.get_host_for_task(task_type)
        if host:
            print(f"{task_type} -> {host.name} ({host.model})")
        else:
            cloud = router.get_cloud_fallback()
            if cloud:
                print(f"{task_type} -> cloud ({cloud.model})")
            else:
                print(f"{task_type} -> NO HOST AVAILABLE")
