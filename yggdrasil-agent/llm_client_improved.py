import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import random
import json

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

@dataclass
class HostFailureInfo:
    """Track failure information for a host"""
    failure_count: int = 0
    last_failure_time: Optional[datetime] = None
    cooldown_until: Optional[datetime] = None

@dataclass
class RetryConfig:
    """Configuration for retry logic"""
    max_attempts: int = 3
    base_delay: float = 1.0  # Base delay in seconds
    max_delay: float = 60.0  # Maximum delay in seconds
    exponential_base: float = 2.0
    jitter: bool = True  # Add random jitter to prevent thundering herd

@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker"""
    failure_threshold: int = 3  # Number of failures before opening circuit
    cooldown_minutes: int = 5   # Minutes to wait before trying again
    reset_timeout: int = 300    # Seconds after which to reset failure count

class LLMHost:
    """Represents an LLM host configuration"""
    def __init__(self, name: str, endpoint: str, host_type: str = "local", timeout: int = 60):
        self.name = name
        self.endpoint = endpoint
        self.host_type = host_type
        self.timeout = timeout
    
    def __str__(self):
        return f"{self.name} ({self.host_type})"

class LLMClient:
    """Enhanced LLM client with timeout, retry, and circuit breaker logic"""
    
    def __init__(self, 
                 hosts: List[LLMHost],
                 default_timeout: int = 60,
                 retry_config: Optional[RetryConfig] = None,
                 circuit_config: Optional[CircuitBreakerConfig] = None):
        """
        Initialize LLMClient with fallback hosts and resilience configurations
        
        Args:
            hosts: List of LLM hosts in fallback order
            default_timeout: Default timeout in seconds for LLM calls
            retry_config: Configuration for retry logic
            circuit_config: Configuration for circuit breaker
        """
        self.hosts = hosts
        self.default_timeout = default_timeout
        self.retry_config = retry_config or RetryConfig()
        self.circuit_config = circuit_config or CircuitBreakerConfig()
        
        # Thread-safe storage for host failure tracking
        self._failure_info: Dict[str, HostFailureInfo] = {}
        self._failure_lock = threading.RLock()
        
        # Thread pool for async operations
        self._executor = ThreadPoolExecutor(max_workers=4)
        
        logger.info(f"Initialized LLMClient with {len(hosts)} hosts: {[str(h) for h in hosts]}")
    
    def _get_failure_info(self, host: LLMHost) -> HostFailureInfo:
        """Thread-safe getter for host failure information"""
        with self._failure_lock:
            if host.name not in self._failure_info:
                self._failure_info[host.name] = HostFailureInfo()
            return self._failure_info[host.name]
    
    def _update_failure_info(self, host: LLMHost, failed: bool = True):
        """Thread-safe update of host failure information"""
        with self._failure_lock:
            info = self._get_failure_info(host)
            current_time = datetime.now()
            
            if failed:
                info.failure_count += 1
                info.last_failure_time = current_time
                
                # Set cooldown if threshold reached
                if info.failure_count >= self.circuit_config.failure_threshold:
                    cooldown_duration = timedelta(minutes=self.circuit_config.cooldown_minutes)
                    info.cooldown_until = current_time + cooldown_duration
                    logger.warning(f"Circuit breaker opened for {host}. Cooldown until {info.cooldown_until}")
            else:
                # Reset on success
                info.failure_count = 0
                info.last_failure_time = None
                info.cooldown_until = None
                logger.debug(f"Reset failure count for {host}")
    
    def _is_host_available(self, host: LLMHost) -> bool:
        """Check if host is available (not in cooldown)"""
        info = self._get_failure_info(host)
        
        if info.cooldown_until is None:
            return True
            
        current_time = datetime.now()
        if current_time >= info.cooldown_until:
            # Cooldown expired, reset the host
            logger.info(f"Cooldown expired for {host}, marking as available")
            self._update_failure_info(host, failed=False)
            return True
        
        logger.debug(f"Host {host} in cooldown until {info.cooldown_until}")
        return False
    
    def _calculate_retry_delay(self, attempt: int) -> float:
        """Calculate delay for exponential backoff with jitter"""
        base_delay = self.retry_config.base_delay
        exponential_delay = base_delay * (self.retry_config.exponential_base ** (attempt - 1))
        delay = min(exponential_delay, self.retry_config.max_delay)
        
        if self.retry_config.jitter:
            # Add ±25% jitter
            jitter = delay * 0.25 * (2 * random.random() - 1)
            delay = max(0, delay + jitter)
        
        return delay
    
    def _make_llm_request(self, host: LLMHost, prompt: str, **kwargs) -> str:
        """
        Make actual LLM request to a host - implement your specific LLM API calls here
        This is a placeholder that simulates different response patterns for testing
        """
        # Simulate network delay and potential failures
        import time
        time.sleep(random.uniform(0.1, 0.5))
        
        # Simulate occasional failures for testing
        if random.random() < 0.3:  # 30% failure rate for simulation
            if host.host_type == "local":
                raise ConnectionError(f"Connection refused to {host.name}")
            else:
                raise TimeoutError(f"Request to {host.name} timed out")
        
        # Simulate successful response
        return f"Response from {host.name}: Generated text for prompt '{prompt[:50]}...'"
    
    def _try_single_host(self, host: LLMHost, prompt: str, task_id: str = None, **kwargs) -> str:
        """
        Attempt to get response from a single host with timeout handling
        
        Args:
            host: LLM host to try
            prompt: Input prompt
            task_id: Optional task identifier for logging
            **kwargs: Additional parameters for LLM call
            
        Returns:
            Generated response string
            
        Raises:
            Exception: If the request fails
        """
        timeout = kwargs.get('timeout', host.timeout or self.default_timeout)
        
        def _request_wrapper():
            return self._make_llm_request(host, prompt, **kwargs)
        
        # Submit request with timeout
        future = self._executor.submit(_request_wrapper)
        
        try:
            result = future.result(timeout=timeout)
            logger.debug(f"[{task_id}] Successful response from {host}")
            return result
        except FuturesTimeoutError:
            future.cancel()  # Attempt to cancel if still running
            raise TimeoutError(f"Request to {host} timed out after {timeout}s")
        except Exception as e:
            logger.debug(f"[{task_id}] Request to {host} failed: {e}")
            raise
    
    def _try_host_with_retry(self, host: LLMHost, prompt: str, task_id: str = None, **kwargs) -> str:
        """
        Try a host with retry logic and exponential backoff
        
        Args:
            host: LLM host to try
            prompt: Input prompt
            task_id: Optional task identifier for logging
            **kwargs: Additional parameters for LLM call
            
        Returns:
            Generated response string
            
        Raises:
            Exception: If all retry attempts fail
        """
        last_exception = None
        
        for attempt in range(1, self.retry_config.max_attempts + 1):
            try:
                logger.debug(f"[{task_id}] Attempt {attempt}/{self.retry_config.max_attempts} for {host}")
                
                result = self._try_single_host(host, prompt, task_id, **kwargs)
                
                # Success - update failure tracking
                self._update_failure_info(host, failed=False)
                return result
                
            except Exception as e:
                last_exception = e
                logger.debug(f"[{task_id}] Retry {attempt}/{self.retry_config.max_attempts} for {host} failed: {e}")
                
                # Don't retry on the last attempt
                if attempt < self.retry_config.max_attempts:
                    delay = self._calculate_retry_delay(attempt)
                    logger.info(f"[{task_id}] Retry {attempt}/{self.retry_config.max_attempts} for {host}, "
                              f"waiting {delay:.2f}s before next attempt")
                    time.sleep(delay)
        
        # All attempts failed - update failure tracking
        self._update_failure_info(host, failed=True)
        raise last_exception
    
    def generate(self, prompt: str, task_id: str = None, **kwargs) -> str:
        """
        Generate response using LLM fallback chain with timeout, retry, and circuit breaker logic
        
        Args:
            prompt: Input prompt for LLM
            task_id: Optional task identifier for logging context
            **kwargs: Additional parameters for LLM calls
            
        Returns:
            Generated response string
            
        Raises:
            Exception: If all hosts fail
        """
        if not task_id:
            task_id = f"task-{int(time.time())}"
        
        logger.info(f"[{task_id}] Starting LLM generation with {len(self.hosts)} hosts")
        
        available_hosts = [host for host in self.hosts if self._is_host_available(host)]
        
        if not available_hosts:
            logger.error(f"[{task_id}] No hosts available (all in circuit breaker cooldown)")
            raise RuntimeError("No LLM hosts available - all hosts are in cooldown")
        
        logger.debug(f"[{task_id}] Available hosts: {[str(h) for h in available_hosts]}")
        
        last_exception = None
        
        for host in available_hosts:
            try:
                logger.info(f"[{task_id}] Trying {host}")
                result = self._try_host_with_retry(host, prompt, task_id, **kwargs)
                logger.info(f"[{task_id}] Successfully got response from {host}")
                return result
                
            except Exception as e:
                last_exception = e
                logger.warning(f"[{task_id}] Host {host} failed after all retries: {e}")
                continue
        
        # All hosts failed
        logger.error(f"[{task_id}] All hosts failed")
        raise RuntimeError(f"All LLM hosts failed. Last error: {last_exception}")
    
    def get_host_status(self) -> Dict[str, Dict[str, Any]]:
        """Get current status of all hosts for debugging"""
        status = {}
        current_time = datetime.now()
        
        with self._failure_lock:
            for host in self.hosts:
                info = self._get_failure_info(host)
                is_available = self._is_host_available(host)
                
                cooldown_remaining = None
                if info.cooldown_until and info.cooldown_until > current_time:
                    cooldown_remaining = (info.cooldown_until - current_time).total_seconds()
                
                status[host.name] = {
                    'type': host.host_type,
                    'endpoint': host.endpoint,
                    'available': is_available,
                    'failure_count': info.failure_count,
                    'last_failure': info.last_failure_time.isoformat() if info.last_failure_time else None,
                    'cooldown_remaining_seconds': cooldown_remaining
                }
        
        return status
    
    def reset_host_failures(self, host_name: str = None):
        """Reset failure tracking for a specific host or all hosts"""
        with self._failure_lock:
            if host_name:
                if host_name in self._failure_info:
                    self._failure_info[host_name] = HostFailureInfo()
                    logger.info(f"Reset failure tracking for {host_name}")
            else:
                self._failure_info.clear()
                logger.info("Reset failure tracking for all hosts")
    
    def close(self):
        """Clean up resources"""
        self._executor.shutdown(wait=True)
        logger.info("LLMClient closed")

# Example usage and testing
def main():
    """Example usage of the improved LLM client"""
    
    # Configure hosts in fallback order (local first, then cloud)
    hosts = [
        LLMHost("local-llama", "http://localhost:11434/api/generate", "local", timeout=30),
        LLMHost("openai-gpt", "https://api.openai.com/v1/completions", "cloud", timeout=60),
        LLMHost("anthropic-claude", "https://api.anthropic.com/v1/complete", "cloud", timeout=60),
    ]
    
    # Configure retry and circuit breaker behavior
    retry_config = RetryConfig(
        max_attempts=3,
        base_delay=1.0,
        max_delay=30.0,
        exponential_base=2.0,
        jitter=True
    )
    
    circuit_config = CircuitBreakerConfig(
        failure_threshold=3,
        cooldown_minutes=5,
        reset_timeout=300
    )
    
    # Initialize client
    client = LLMClient(
        hosts=hosts,
        default_timeout=60,
        retry_config=retry_config,
        circuit_config=circuit_config
    )
    
    try:
        # Example usage
        prompt = "Explain the concept of machine learning in simple terms."
        task_id = "demo-task-001"
        
        print(f"\n=== Attempting LLM generation ===")
        response = client.generate(prompt, task_id=task_id)
        print(f"Response: {response}")
        
        print(f"\n=== Host Status ===")
        status = client.get_host_status()
        print(json.dumps(status, indent=2))
        
    except Exception as e:
        print(f"Generation failed: {e}")
        
        print(f"\n=== Host Status After Failure ===")
        status = client.get_host_status()
        print(json.dumps(status, indent=2))
    
    finally:
        client.close()

if __name__ == "__main__":
    main()