#!/usr/bin/env python3
"""
Structured observability for task dispatcher.

Provides:
1. JSON structured logging with task context
2. Prometheus-compatible metrics collection
3. Error tracking with full tracebacks
4. Retry logic with exponential backoff
"""

import json
import logging
import time
import traceback
from typing import Dict, Any, Optional, Callable, TypeVar, Awaitable
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from enum import Enum
from logging.handlers import RotatingFileHandler
import asyncio

T = TypeVar('T')


class TaskStatus(Enum):
    """Task execution status"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRY = "retry"
    TIMEOUT = "timeout"
    BLOCKED = "blocked"


@dataclass
class TaskMetrics:
    """Metrics for a single task execution"""
    task_id: str
    task_type: str
    host: str
    status: TaskStatus
    start_time: float
    end_time: float
    duration_ms: float
    attempt: int = 1
    max_attempts: int = 3
    
    # LLM-specific metrics
    tokens_in: int = 0
    tokens_out: int = 0
    
    # Error tracking
    error_message: Optional[str] = None
    error_traceback: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/storage"""
        return {
            'task_id': self.task_id,
            'task_type': self.task_type,
            'host': self.host,
            'status': self.status.value,
            'duration_ms': self.duration_ms,
            'attempt': self.attempt,
            'max_attempts': self.max_attempts,
            'tokens_in': self.tokens_in,
            'tokens_out': self.tokens_out,
            'error': self.error_message,
            'timestamp': datetime.fromtimestamp(self.start_time, tz=timezone.utc).isoformat(),
        }


class StructuredLogger:
    """JSON-structured logging with task context"""
    
    def __init__(self, name: str, output_file: Optional[Path] = None, max_bytes: int = 10485760, backup_count: int = 5):
        """
        Initialize structured logger.
        
        Args:
            name: Logger name
            output_file: Path to output file
            max_bytes: Max size for rotating log file (default 10MB)
            backup_count: Number of backup files to keep (default 5)
        """
        self.logger = logging.getLogger(name)
        self.output_file = output_file
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        
        if output_file:
            # Ensure directory exists
            output_file.parent.mkdir(parents=True, exist_ok=True)
            # Set up rotating file handler if file specified
            self._setup_rotating_handler(output_file)
    
    def _setup_rotating_handler(self, output_file: Path) -> None:
        """Set up rotating file handler for the logger"""
        try:
            handler = RotatingFileHandler(
                str(output_file),
                maxBytes=self.max_bytes,
                backupCount=self.backup_count,
            )
            formatter = logging.Formatter('%(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
        except Exception as e:
            logging.warning(f"Failed to set up rotating handler: {e}")
    
    def log_task_event(
        self,
        level: str,
        task_id: str,
        event: str,
        **kwargs
    ) -> None:
        """
        Log a task event with structured context.
        
        Args:
            level: 'info', 'warning', 'error', etc.
            task_id: Task ID for context
            event: Event description
            **kwargs: Additional context fields
        """
        log_entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'task_id': task_id,
            'event': event,
            'level': level,
            **kwargs,
        }
        
        # Log to standard logger (uses rotating handler if configured)
        log_message = json.dumps(log_entry)
        getattr(self.logger, level.lower())(log_message)
    
    def log_metrics(self, metrics: TaskMetrics) -> None:
        """Log task metrics"""
        self.log_task_event(
            level='info',
            task_id=metrics.task_id,
            event='task_completed',
            **metrics.to_dict()
        )


class MetricsCollector:
    """Prometheus-style metrics collection"""
    
    def __init__(self):
        self.tasks_total = {}  # {host: {status: count}}
        self.tasks_duration = {}  # {host: [durations]}
        self.host_active = {}  # {host: count}
        self.token_usage = {}  # {host: {in: count, out: count}}
        self.start_time = time.time()
    
    def record_task_completion(self, metrics: TaskMetrics) -> None:
        """Record task completion metrics"""
        host = metrics.host
        status = metrics.status.value
        
        # Task count by status
        if host not in self.tasks_total:
            self.tasks_total[host] = {}
        self.tasks_total[host][status] = self.tasks_total[host].get(status, 0) + 1
        
        # Duration tracking
        if host not in self.tasks_duration:
            self.tasks_duration[host] = []
        self.tasks_duration[host].append(metrics.duration_ms)
        
        # Token usage
        if host not in self.token_usage:
            self.token_usage[host] = {'in': 0, 'out': 0}
        self.token_usage[host]['in'] += metrics.tokens_in
        self.token_usage[host]['out'] += metrics.tokens_out
    
    def get_percentile(self, host: str, percentile: int = 50) -> float:
        """Get latency percentile for host"""
        if host not in self.tasks_duration or not self.tasks_duration[host]:
            return 0.0
        
        durations = sorted(self.tasks_duration[host])
        index = int(len(durations) * percentile / 100)
        return durations[index]
    
    def export_prometheus(self) -> str:
        """Export metrics in Prometheus format"""
        output = []
        output.append("# HELP ygg_tasks_total Task completion count")
        output.append("# TYPE ygg_tasks_total counter")
        
        for host, statuses in self.tasks_total.items():
            for status, count in statuses.items():
                output.append(
                    f'ygg_tasks_total{{host="{host}",status="{status}"}} {count}'
                )
        
        output.append("")
        output.append("# HELP ygg_task_duration_ms Task duration in milliseconds")
        output.append("# TYPE ygg_task_duration_ms gauge")
        
        for host in self.tasks_duration.keys():
            p50 = self.get_percentile(host, 50)
            p95 = self.get_percentile(host, 95)
            p99 = self.get_percentile(host, 99)
            
            output.append(f'ygg_task_duration_ms{{host="{host}",percentile="50"}} {p50}')
            output.append(f'ygg_task_duration_ms{{host="{host}",percentile="95"}} {p95}')
            output.append(f'ygg_task_duration_ms{{host="{host}",percentile="99"}} {p99}')
        
        output.append("")
        output.append("# HELP ygg_tokens_total Token usage counter")
        output.append("# TYPE ygg_tokens_total counter")
        
        for host, tokens in self.token_usage.items():
            output.append(f'ygg_tokens_total{{host="{host}",type="input"}} {tokens["in"]}')
            output.append(f'ygg_tokens_total{{host="{host}",type="output"}} {tokens["out"]}')
        
        output.append("")
        output.append("# HELP ygg_uptime_seconds Dispatcher uptime")
        output.append("# TYPE ygg_uptime_seconds gauge")
        uptime = time.time() - self.start_time
        output.append(f'ygg_uptime_seconds {uptime}')
        
        return '\n'.join(output)
    
    def export_json(self) -> Dict[str, Any]:
        """Export metrics as JSON"""
        return {
            'tasks': self.tasks_total,
            'latency_ms': {
                host: {
                    'p50': self.get_percentile(host, 50),
                    'p95': self.get_percentile(host, 95),
                    'p99': self.get_percentile(host, 99),
                }
                for host in self.tasks_duration.keys()
            },
            'tokens': self.token_usage,
            'uptime_seconds': time.time() - self.start_time,
        }


class RetryPolicy:
    """Exponential backoff retry configuration"""
    
    def __init__(
        self,
        max_attempts: int = 3,
        initial_delay_ms: int = 100,
        max_delay_ms: int = 5000,
        exponential_base: float = 2.0,
        jitter: bool = True,
    ):
        self.max_attempts = max_attempts
        self.initial_delay_ms = initial_delay_ms
        self.max_delay_ms = max_delay_ms
        self.exponential_base = exponential_base
        self.jitter = jitter
    
    def get_delay_ms(self, attempt: int) -> int:
        """
        Calculate delay for attempt (0-indexed).
        
        Formula: min(initial * base^attempt, max_delay)
        With optional jitter: delay * (0.5..1.5)
        """
        delay = self.initial_delay_ms * (self.exponential_base ** attempt)
        delay = min(delay, self.max_delay_ms)
        
        if self.jitter:
            import random
            delay *= random.uniform(0.5, 1.5)
        
        return int(delay)
    
    def should_retry(self, attempt: int, error: Exception) -> bool:
        """
        Determine if error is retryable.
        
        Retryable: timeouts, network errors, transient GPU errors
        Non-retryable: validation errors, invalid prompts
        """
        if attempt >= self.max_attempts:
            return False
        
        # Check error type and message
        error_type = type(error).__name__.lower()
        error_str = str(error).lower()
        
        # Non-retryable error types
        non_retryable_types = [
            'valueerror',
            'typeerror',
            'attributeerror',
            'keyerror',
            'indexerror',
            'jsondecoder',
        ]
        for pattern in non_retryable_types:
            if pattern in error_type:
                return False
        
        # Non-retryable error messages
        non_retryable_msgs = [
            'invalid prompt',
            'invalid json',
            'decode error',
        ]
        for pattern in non_retryable_msgs:
            if pattern in error_str:
                return False
        
        # Retryable errors
        retryable = [
            'timeout',
            'connection reset',
            'connection refused',
            'broken pipe',
            'gpu memory',
            'cuda out of memory',
            'out of memory',
        ]
        for pattern in retryable:
            if pattern in error_str:
                return True
        
        # Default: retry on unknown errors (transient by default)
        return True


async def with_retry(
    func: Callable[..., Awaitable[T]],
    *args,
    policy: Optional[RetryPolicy] = None,
    logger: Optional[StructuredLogger] = None,
    task_id: Optional[str] = None,
    **kwargs
) -> T:
    """
    Execute async function with retry logic.
    
    Args:
        func: Async function to call
        args: Positional arguments
        policy: RetryPolicy (uses defaults if None)
        logger: StructuredLogger for logging retries
        task_id: Task ID for logging context
        kwargs: Keyword arguments
    
    Returns:
        Result of func
    
    Raises:
        Last exception if all retries exhausted
    """
    if policy is None:
        policy = RetryPolicy()
    
    last_error = None
    
    for attempt in range(policy.max_attempts):
        try:
            return await func(*args, **kwargs)
        
        except Exception as e:
            last_error = e
            
            if not policy.should_retry(attempt, e):
                # Non-retryable error, raise immediately
                if logger and task_id:
                    logger.log_task_event(
                        'error',
                        task_id,
                        'task_failed_non_retryable',
                        attempt=attempt + 1,
                        error=str(e),
                    )
                raise
            
            if attempt < policy.max_attempts - 1:
                delay_ms = policy.get_delay_ms(attempt)
                if logger and task_id:
                    logger.log_task_event(
                        'warning',
                        task_id,
                        'task_retry_scheduled',
                        attempt=attempt + 1,
                        delay_ms=delay_ms,
                        error=str(e),
                    )
                
                await asyncio.sleep(delay_ms / 1000.0)
            else:
                # Last attempt failed
                if logger and task_id:
                    logger.log_task_event(
                        'error',
                        task_id,
                        'task_failed_max_retries',
                        attempt=attempt + 1,
                        error=str(e),
                    )
    
    # All retries exhausted
    raise last_error or Exception("Unknown error")


class ErrorTracker:
    """Track and store error details for post-mortem analysis"""
    
    def __init__(self, error_log_path: Optional[Path] = None):
        self.error_log_path = error_log_path
        if error_log_path:
            error_log_path.parent.mkdir(parents=True, exist_ok=True)
    
    def track_error(
        self,
        task_id: str,
        error: Exception,
        context: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        Track error with full context for post-mortem.
        
        Returns dict suitable for storing in Beads result field.
        """
        error_record = {
            'task_id': task_id,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'error_type': type(error).__name__,
            'error_message': str(error),
            'traceback': traceback.format_exc(),
            'context': context or {},
        }
        
        # Log to file if configured
        if self.error_log_path:
            try:
                with open(self.error_log_path, 'a') as f:
                    f.write(json.dumps(error_record) + '\n')
            except Exception as e:
                logging.error(f"Failed to write error log: {e}")
        
        return error_record
    
    def format_for_beads(self, error_record: Dict[str, Any]) -> str:
        """Format error record for Beads result field"""
        return f"""ERROR REPORT
========================================
Task ID: {error_record['task_id']}
Time: {error_record['timestamp']}
Type: {error_record['error_type']}
Message: {error_record['error_message']}

Traceback:
{error_record['traceback']}

Context:
{json.dumps(error_record['context'], indent=2)}
"""


# Global instances (initialized by dispatcher)
structured_logger: Optional[StructuredLogger] = None
metrics: Optional[MetricsCollector] = None
error_tracker: Optional[ErrorTracker] = None


def init_observability(
    log_dir: Path = None,
    enable_metrics: bool = True,
    enable_error_tracking: bool = True,
) -> None:
    """
    Initialize global observability components.
    
    Args:
        log_dir: Directory for logs (defaults to ~/.cache/yggdrasil)
        enable_metrics: Enable metrics collection
        enable_error_tracking: Enable error tracking
    """
    global structured_logger, metrics, error_tracker
    
    if log_dir is None:
        log_dir = Path.home() / '.cache/yggdrasil'
    
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize structured logger
    structured_logger = StructuredLogger(
        'yggdrasil.dispatcher',
        output_file=log_dir / 'dispatcher.jsonl'
    )
    
    # Initialize metrics
    if enable_metrics:
        metrics = MetricsCollector()
    
    # Initialize error tracker
    if enable_error_tracking:
        error_tracker = ErrorTracker(log_dir / 'errors.jsonl')


def get_structured_logger() -> StructuredLogger:
    """Get or initialize structured logger"""
    global structured_logger
    if structured_logger is None:
        init_observability()
    return structured_logger


def get_metrics() -> MetricsCollector:
    """Get or initialize metrics collector"""
    global metrics
    if metrics is None:
        init_observability()
    return metrics


def get_error_tracker() -> ErrorTracker:
    """Get or initialize error tracker"""
    global error_tracker
    if error_tracker is None:
        init_observability()
    return error_tracker


class MetricsExporter:
    """
    HTTP metrics exporter for Prometheus scraping.
    
    Provides a simple HTTP endpoint at /metrics that exports metrics in Prometheus format.
    """
    
    def __init__(self, port: int = 8888, host: str = '0.0.0.0'):
        """
        Initialize metrics exporter.
        
        Args:
            port: Port to listen on (default 8888)
            host: Host to bind to (default 0.0.0.0)
        """
        self.port = port
        self.host = host
        self.server = None
        
    async def start(self) -> None:
        """Start metrics HTTP server (async)"""
        try:
            from aiohttp import web
            
            app = web.Application()
            app.router.add_get('/metrics', self._metrics_handler)
            
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, self.host, self.port)
            await site.start()
            
            logging.info(f"Metrics exporter started on http://{self.host}:{self.port}/metrics")
            self.server = runner
        except ImportError:
            logging.warning("aiohttp not installed, metrics exporter disabled")
    
    async def stop(self) -> None:
        """Stop metrics HTTP server"""
        if self.server:
            await self.server.cleanup()
    
    async def _metrics_handler(self, request) -> 'web.Response':
        """Handle /metrics request"""
        from aiohttp import web
        
        metrics_collector = get_metrics()
        if not metrics_collector:
            return web.Response(text="# No metrics available\n")
        
        # Format metrics in Prometheus format
        lines = [
            "# HELP yggdrasil_tasks_total Total number of tasks processed",
            "# TYPE yggdrasil_tasks_total counter",
        ]
        
        stats = metrics_collector.get_stats()
        lines.append(f'yggdrasil_tasks_total{{status="completed"}} {stats["completed"]}')
        lines.append(f'yggdrasil_tasks_total{{status="failed"}} {stats["failed"]}')
        
        lines.extend([
            "",
            "# HELP yggdrasil_latency_ms Task processing latency in milliseconds",
            "# TYPE yggdrasil_latency_ms gauge",
            f'yggdrasil_latency_ms{{quantile="p50"}} {stats.get("latency_p50", 0)}',
            f'yggdrasil_latency_ms{{quantile="p95"}} {stats.get("latency_p95", 0)}',
            f'yggdrasil_latency_ms{{quantile="p99"}} {stats.get("latency_p99", 0)}',
            "",
            "# HELP yggdrasil_tokens_total Total tokens processed",
            "# TYPE yggdrasil_tokens_total counter",
            f'yggdrasil_tokens_total{{direction="input"}} {stats.get("tokens_in", 0)}',
            f'yggdrasil_tokens_total{{direction="output"}} {stats.get("tokens_out", 0)}',
        ])
        
        return web.Response(text="\n".join(lines) + "\n")
