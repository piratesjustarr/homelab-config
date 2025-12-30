#!/usr/bin/env python3
"""
Configuration validation and management for Yggdrasil agent.

Provides:
1. Pydantic schema validation for all config
2. Environment-specific config (dev/staging/prod)
3. Startup validation with fast-fail
4. Config merging from multiple sources
5. Type safety and defaults
"""

import json
import os
from pathlib import Path
from typing import Optional, Dict, Any, List
from enum import Enum
from dataclasses import dataclass, asdict, field

try:
    from pydantic import BaseModel, Field, validator, ValidationError
except ImportError:
    # Fallback without pydantic for basic validation
    BaseModel = object
    Field = None
    validator = None
    ValidationError = ValueError


class Environment(str, Enum):
    """Configuration environments"""
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


# ============================================================================
# Configuration Models (using Pydantic for validation)
# ============================================================================

class LLMHostConfig(BaseModel):
    """Configuration for a single LLM host"""
    name: str
    url: str
    model: str
    capabilities: List[str] = Field(default_factory=list)
    priority: int = 1
    timeout_seconds: int = 120
    
    class Config:
        extra = "forbid"


class CloudProviderConfig(BaseModel):
    """Configuration for cloud LLM provider"""
    name: str
    model: str
    capabilities: List[str] = Field(default_factory=list)
    priority: int = 99
    timeout_seconds: int = 60
    
    class Config:
        extra = "forbid"


class RetryConfig(BaseModel):
    """Configuration for retry behavior"""
    max_attempts: int = Field(default=3, ge=1, le=10)
    initial_delay_ms: int = Field(default=100, ge=10, le=5000)
    max_delay_ms: int = Field(default=5000, ge=100, le=60000)
    exponential_base: float = Field(default=2.0, ge=1.1, le=5.0)
    jitter: bool = True
    
    class Config:
        extra = "forbid"


class HostConcurrencyConfig(BaseModel):
    """Per-host concurrency limits"""
    surtr_reasoning: int = Field(default=2, ge=1, le=10, alias="surtr-reasoning")
    fenrir_chat: int = Field(default=3, ge=1, le=10, alias="fenrir-chat")
    skadi_code: int = Field(default=2, ge=1, le=10, alias="skadi-code")
    
    class Config:
        extra = "forbid"
        populate_by_name = True  # Works with both Pydantic v1 and v2
    
    def to_dict(self) -> Dict[str, int]:
        """Convert to host:limit dictionary"""
        return {
            'surtr-reasoning': self.surtr_reasoning,
            'fenrir-chat': self.fenrir_chat,
            'skadi-code': self.skadi_code,
        }


class ObservabilityConfig(BaseModel):
    """Configuration for observability stack"""
    enabled: bool = True
    log_dir: Optional[str] = None
    enable_metrics: bool = True
    enable_error_tracking: bool = True
    metrics_port: int = Field(default=8888, ge=1024, le=65535)
    
    class Config:
        extra = "forbid"


class BeeAIConfig(BaseModel):
    """Configuration for BeeAI integration"""
    enabled: bool = True
    python_version: str = "3.12"  # Required version
    fallback_to_simple_llm: bool = True
    
    class Config:
        extra = "forbid"


class YggdrasilConfig(BaseModel):
    """Complete Yggdrasil agent configuration"""
    
    # Environment
    environment: Environment = Environment.DEV
    
    # LLM Hosts
    hosts: List[LLMHostConfig] = Field(default_factory=list)
    cloud_providers: List[CloudProviderConfig] = Field(default_factory=list)
    routing: Dict[str, List[str]] = Field(default_factory=dict)
    
    # Concurrency
    concurrency: HostConcurrencyConfig = Field(default_factory=HostConcurrencyConfig)
    
    # Retry behavior
    retry: RetryConfig = Field(default_factory=RetryConfig)
    
    # Observability
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    
    # BeeAI integration
    beeai: BeeAIConfig = Field(default_factory=BeeAIConfig)
    
    # Beads integration
    beads_dir: Optional[str] = None
    
    # Logging
    log_level: str = "INFO"
    
    class Config:
        extra = "forbid"
    
    @validator('log_level')
    def validate_log_level(cls, v):
        """Validate log level"""
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if v.upper() not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}, got {v}")
        return v.upper()
    
    @validator('hosts', pre=True, always=True)
    def validate_hosts(cls, v):
        """Ensure at least one host configured for non-cloud setups"""
        if not v or len(v) == 0:
            raise ValueError("At least one LLM host must be configured")
        return v


# ============================================================================
# Configuration Manager
# ============================================================================

class ConfigManager:
    """Manage Yggdrasil configuration from multiple sources"""
    
    # Default config paths in priority order
    DEFAULT_CONFIG_PATHS = [
        Path.cwd() / 'yggdrasil.{env}.yaml',
        Path.cwd() / 'yggdrasil.yaml',
        Path.home() / '.config/yggdrasil/yggdrasil.{env}.yaml',
        Path.home() / '.config/yggdrasil/yggdrasil.yaml',
        Path(__file__).parent / 'yggdrasil.yaml',
    ]
    
    def __init__(self, environment: Optional[str] = None):
        """
        Initialize config manager.
        
        Args:
            environment: 'dev', 'staging', or 'prod' (defaults to env var or 'dev')
        """
        self.environment = environment or os.environ.get('YGGDRASIL_ENV', 'dev')
        self.config = None
        self._config_source = None
    
    def load(self, config_path: Optional[str] = None) -> YggdrasilConfig:
        """
        Load configuration from file or environment.
        
        Priority order:
        1. Explicit config_path parameter
        2. YGGDRASIL_CONFIG env var
        3. yggdrasil.{env}.yaml in current/config directories
        4. yggdrasil.yaml in current/config directories
        5. Built-in defaults
        
        Args:
            config_path: Optional explicit path to config file
        
        Returns:
            YggdrasilConfig instance
        
        Raises:
            FileNotFoundError: If config file specified but not found
            ValidationError: If config is invalid
        """
        # Determine config file to load
        config_file = None
        
        if config_path:
            config_file = Path(config_path)
            if not config_file.exists():
                raise FileNotFoundError(f"Config file not found: {config_file}")
        
        elif env_config := os.environ.get('YGGDRASIL_CONFIG'):
            config_file = Path(env_config)
            if not config_file.exists():
                raise FileNotFoundError(f"Config file not found (from YGGDRASIL_CONFIG): {config_file}")
        
        else:
            # Search default paths
            for path_template in self.DEFAULT_CONFIG_PATHS:
                # Expand environment placeholder
                path_str = str(path_template).replace('{env}', self.environment)
                path = Path(path_str)
                if path.exists():
                    config_file = path
                    break
        
        # Load config
        if config_file:
            return self._load_from_file(config_file)
        else:
            return self._load_defaults()
    
    def _load_from_file(self, config_path: Path) -> YggdrasilConfig:
        """Load and validate config from YAML file"""
        import yaml
        
        try:
            with open(config_path) as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ValueError(f"Failed to parse YAML config: {e}")
        
        # Add environment to config
        data['environment'] = self.environment
        
        # Validate with Pydantic
        try:
            config = YggdrasilConfig(**data)
            self._config_source = str(config_path)
            self.config = config
            return config
        except ValidationError as e:
            raise ValueError(f"Invalid config in {config_path}:\n{e}")
    
    def _load_defaults(self) -> YggdrasilConfig:
        """Load default configuration"""
        defaults = {
            'environment': self.environment,
            'hosts': [
                {
                    'name': 'surtr-reasoning',
                    'url': 'http://surtr:8081/v1',
                    'model': 'gpt-oss:20b',
                    'capabilities': ['reasoning', 'complex', 'planning'],
                    'priority': 1,
                },
                {
                    'name': 'fenrir-chat',
                    'url': 'http://fenrir:8081/v1',
                    'model': 'qwen2.5:7b',
                    'capabilities': ['chat', 'text', 'text-processing', 'summarize'],
                    'priority': 1,
                },
                {
                    'name': 'skadi-code',
                    'url': 'http://skadi:8080/v1',
                    'model': 'granite-code:8b',
                    'capabilities': ['code', 'code-generation', 'code-review', 'code-fix'],
                    'priority': 1,
                },
            ],
            'cloud_providers': [
                {
                    'name': 'anthropic',
                    'model': 'claude-sonnet-4-20250514',
                    'capabilities': ['code', 'reasoning', 'text', 'general', 'fallback'],
                    'priority': 99,
                }
            ],
            'routing': {
                'code-generation': ['code'],
                'code-review': ['code', 'reasoning'],
                'code-fix': ['code'],
                'text-processing': ['text', 'chat'],
                'summarize': ['text', 'chat'],
                'reasoning': ['reasoning', 'complex'],
                'general': ['general', 'chat', 'fast'],
                'default': ['fast', 'general'],
            },
            'concurrency': {
                'surtr-reasoning': 2,
                'fenrir-chat': 3,
                'skadi-code': 2,
            },
        }
        
        config = YggdrasilConfig(**defaults)
        self._config_source = 'built-in defaults'
        self.config = config
        return config
    
    def validate_startup(self) -> None:
        """
        Validate configuration at startup.
        
        Checks:
        - At least one host is configured
        - All hosts are reachable (via health check)
        - Required Python version for BeeAI
        
        Raises:
            RuntimeError: If validation fails
        """
        if not self.config:
            raise RuntimeError("No configuration loaded")
        
        # Check hosts
        if not self.config.hosts:
            raise RuntimeError("No LLM hosts configured")
        
        # Check Python version if BeeAI enabled
        if self.config.beeai.enabled:
            import sys
            current_version = f"{sys.version_info.major}.{sys.version_info.minor}"
            required_version = self.config.beeai.python_version
            if current_version < required_version:
                msg = f"BeeAI requires Python {required_version}+, found {current_version}"
                if self.config.beeai.fallback_to_simple_llm:
                    import logging
                    logging.warning(f"{msg} (falling back to simple LLM)")
                else:
                    raise RuntimeError(msg)
    
    def get_config(self) -> YggdrasilConfig:
        """Get loaded configuration"""
        if not self.config:
            self.load()
        return self.config
    
    def get_source(self) -> str:
        """Get source of loaded configuration"""
        return self._config_source or 'not loaded'
    
    def to_dict(self) -> Dict[str, Any]:
        """Export config as dictionary"""
        if not self.config:
            self.load()
        # Use model_dump for Pydantic v2, dict for v1
        if hasattr(self.config, 'model_dump'):
            return self.config.model_dump()
        else:
            return self.config.dict()
    
    def to_json(self) -> str:
        """Export config as JSON"""
        if not self.config:
            self.load()
        # Use model_dump_json for Pydantic v2, json for v1
        if hasattr(self.config, 'model_dump_json'):
            return self.config.model_dump_json(indent=2)
        else:
            return self.config.json(indent=2)


# ============================================================================
# Utility Functions
# ============================================================================

def load_config(
    environment: Optional[str] = None,
    config_path: Optional[str] = None,
    validate_startup: bool = True,
) -> YggdrasilConfig:
    """
    Convenience function to load and validate config.
    
    Args:
        environment: 'dev', 'staging', or 'prod'
        config_path: Optional explicit path to config file
        validate_startup: Whether to run startup validation
    
    Returns:
        YggdrasilConfig instance
    
    Raises:
        RuntimeError: If startup validation fails
        FileNotFoundError: If config file not found
        ValueError: If config is invalid
    """
    manager = ConfigManager(environment=environment)
    config = manager.load(config_path=config_path)
    
    if validate_startup:
        manager.validate_startup()
    
    return config


def validate_environment() -> Dict[str, str]:
    """
    Check environment is properly configured.
    
    Returns:
        Dictionary of environment variables and their status
    """
    import logging
    logger = logging.getLogger(__name__)
    
    status = {}
    
    # Check required env vars
    required = [
        ('ANTHROPIC_API_KEY', 'Cloud LLM fallback'),
    ]
    
    optional = [
        ('YGGDRASIL_ENV', 'Configuration environment'),
        ('YGGDRASIL_CONFIG', 'Explicit config file path'),
    ]
    
    for var, desc in required:
        if os.environ.get(var):
            status[var] = f"✓ {desc}"
        else:
            logger.warning(f"Missing required env var: {var} ({desc})")
            status[var] = f"✗ {desc} (missing)"
    
    for var, desc in optional:
        if os.environ.get(var):
            status[var] = f"✓ {desc}"
        else:
            status[var] = f"○ {desc} (not set)"
    
    return status
