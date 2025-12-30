# Configuration & BeeAI Integration Guide

**Status**: ✅ Configuration validation and BeeAI integration complete

## Configuration System

### Overview

Yggdrasil now includes a complete configuration management system with:

- **Pydantic-based validation** - Type-safe configuration with automatic validation
- **Environment-specific configs** - Separate YAML files for dev/staging/prod
- **Runtime validation** - Fast-fail on missing or invalid configuration
- **Schema documentation** - All config options validated against schema

### Configuration Sources

Configuration loaded in priority order:

1. **Explicit path**: `load_config(config_path='/custom/path/yggdrasil.yaml')`
2. **Environment variable**: `YGGDRASIL_CONFIG=/path/to/config.yaml`
3. **Environment-specific file**: `yggdrasil.{env}.yaml` (dev/staging/prod)
4. **Default file**: `yggdrasil.yaml`
5. **Built-in defaults**: If no file found

### Environments

Three predefined environments:

```
yggdrasil.dev.yaml      # Development (conservative limits)
yggdrasil.staging.yaml  # Staging (moderate limits, test BeeAI)
yggdrasil.prod.yaml     # Production (high concurrency, optimized)
```

### Using Configuration

```python
from config import load_config

# Load with automatic validation
config = load_config(
    environment='prod',  # 'dev', 'staging', or 'prod'
    validate_startup=True,  # Fail fast on bad config
)

# Access config values
print(config.concurrency.to_dict())
print(config.retry.max_attempts)
print(config.beeai.enabled)
```

### Configuration Schema

#### Concurrency Limits
```yaml
concurrency:
  surtr-reasoning: 2    # Max 2 concurrent reasoning tasks
  fenrir-chat: 3        # Max 3 concurrent text tasks
  skadi-code: 2         # Max 2 concurrent code tasks
```

#### Retry Policy
```yaml
retry:
  max_attempts: 3           # Number of retries
  initial_delay_ms: 100     # First delay
  max_delay_ms: 5000        # Maximum delay
  exponential_base: 2.0     # Backoff multiplier
  jitter: true              # Add randomness
```

#### LLM Hosts
```yaml
hosts:
  - name: surtr-reasoning
    url: http://surtr:8081/v1
    model: gpt-oss:20b
    capabilities: [reasoning, complex]
    priority: 1
    timeout_seconds: 120
```

#### Observability
```yaml
observability:
  enabled: true
  log_dir: ~/.cache/yggdrasil
  enable_metrics: true
  enable_error_tracking: true
  metrics_port: 8888
```

#### BeeAI Integration
```yaml
beeai:
  enabled: true              # Enable/disable BeeAI
  python_version: "3.12"     # Minimum Python version
  fallback_to_simple_llm: true  # Fall back if BeeAI unavailable
```

### Validation

Configuration is automatically validated on load:

```python
from config import load_config, ValidationError

try:
    config = load_config()
except ValidationError as e:
    print(f"Invalid config: {e}")
```

Validation checks:

- ✓ All required fields present
- ✓ All values within valid ranges
- ✓ At least one LLM host configured
- ✓ Python version compatible with BeeAI (if enabled)
- ✓ Type safety for all fields

### Startup Validation

```python
from config import load_config

config = load_config(validate_startup=True)

# Checks:
# - At least one host configured
# - Python version meets BeeAI requirements
# - (Future: health checks on hosts)
```

## BeeAI Integration

### Overview

BeeAI agent framework provides structured agent capabilities:

- **CodeGenerationAgent** - Code generation and refactoring
- **TextProcessingAgent** - Text extraction, summarization, rewriting
- **ReasoningAgent** - Complex analysis and planning

### Architecture

```
AsyncYggdrasilAgent
  └─ BeeAIManager
     ├─ CodeGenerationAgent (if Python 3.12+ and beeai-framework available)
     ├─ TextProcessingAgent
     └─ ReasoningAgent
     
     Falls back to simple LLM if:
     - Python < 3.12
     - beeai-framework not installed
     - Agents fail to initialize
```

### Enabling BeeAI

In `yggdrasil.staging.yaml` or `yggdrasil.prod.yaml`:

```yaml
beeai:
  enabled: true
  python_version: "3.12"
  fallback_to_simple_llm: true  # Graceful degradation
```

### Installation

BeeAI requires Python 3.12+ and the beeai-framework package:

```bash
# Check Python version
python --version  # Must be 3.12+

# Install BeeAI framework
pip install beeai-framework
```

### Usage in Code

```python
from config import load_config
from beeai_integration import initialize_beeai

# Load config with BeeAI enabled
config = load_config()

# Initialize BeeAI
beeai = initialize_beeai(
    config=config.beeai.dict(),
    llm_router=llm_router,
    cloud_llm=cloud_llm,
)

# Check if BeeAI available
if beeai.is_available():
    # Use BeeAI agents
    agent = beeai.get_agent('code')
    result = await agent.process(prompt)
else:
    # Fallback to simple LLM (automatic)
    pass
```

### Fallback Behavior

If BeeAI unavailable:

```python
beeai:
  enabled: true
  fallback_to_simple_llm: true   # ← Allows fallback
```

Then:
1. If Python < 3.12: Warning logged, simple LLM used
2. If beeai-framework missing: Warning logged, simple LLM used
3. If agents fail to initialize: Warning logged, simple LLM used

With `fallback_to_simple_llm: false`, startup fails fast on any issue.

## Using Config in Dispatcher

### Integration with AsyncYggdrasilAgent

```python
from config import load_config
from async_dispatcher import AsyncYggdrasilAgent

# Load config
config = load_config(
    environment=os.environ.get('YGGDRASIL_ENV', 'dev')
)

# Pass to agent
agent = AsyncYggdrasilAgent(
    beads_dir=config.beads_dir,
    enable_observability=config.observability.enabled,
)

# Agent automatically uses:
# - config.concurrency for host limits
# - config.retry for retry policy
# - config.beeai for BeeAI setup
# - config.observability for logging/metrics
```

### CLI Usage

```bash
# Use default config (built-in defaults)
python ygg.py loop --async

# Use specific environment
export YGGDRASIL_ENV=prod
python ygg.py loop --async

# Use custom config file
export YGGDRASIL_CONFIG=/etc/yggdrasil/custom.yaml
python ygg.py loop --async
```

## Configuration Examples

### Development Setup

```yaml
# yggdrasil.dev.yaml
environment: dev
log_level: DEBUG

concurrency:
  surtr-reasoning: 1
  fenrir-chat: 1
  skadi-code: 1

beeai:
  enabled: false  # Disabled in dev for simplicity

retry:
  initial_delay_ms: 50  # Shorter delays for testing
```

### Production Setup

```yaml
# yggdrasil.prod.yaml
environment: prod
log_level: INFO

concurrency:
  surtr-reasoning: 2
  fenrir-chat: 3
  skadi-code: 2

observability:
  log_dir: /var/log/yggdrasil
  enable_metrics: true
  enable_error_tracking: true

beeai:
  enabled: true  # Enabled in prod
  fallback_to_simple_llm: true
```

## Files

### New Implementation
- `config.py` (450 lines) - Configuration system with Pydantic validation
- `beeai_integration.py` (300 lines) - BeeAI manager with fallback support

### Configuration Files
- `yggdrasil.dev.yaml` - Development environment config
- `yggdrasil.staging.yaml` - Staging environment config
- `yggdrasil.prod.yaml` - Production environment config

## Testing Configuration

```bash
# Test loading dev config
python -c "from config import load_config; load_config('dev')"

# Test validation
python -c "from config import load_config; load_config(validate_startup=True)"

# Test environment detection
export YGGDRASIL_ENV=staging
python -c "from config import load_config; print(load_config().environment)"
```

## Environment Variables

```bash
# Set environment
export YGGDRASIL_ENV=prod

# Set custom config file
export YGGDRASIL_CONFIG=/etc/yggdrasil/custom.yaml

# Set cloud API key
export ANTHROPIC_API_KEY=sk-...
```

## Troubleshooting

### "Invalid config: ..."

Check configuration against schema in OBSERVABILITY.md. Ensure:
- All required fields present
- Values within valid ranges
- YAML syntax correct

### "Python version < 3.12, BeeAI disabled"

Update Python:
```bash
# Check current version
python --version

# Use Python 3.12+ explicitly
python3.12 ygg.py loop --async
```

### "beeai-framework not installed"

Install BeeAI framework:
```bash
pip install beeai-framework
```

Or use `fallback_to_simple_llm: true` in config.

## Next Steps

1. **Review config files** - Check yggdrasil.dev/staging/prod.yaml
2. **Test configuration loading** - Run examples above
3. **Set environment variables** - Configure for your environment
4. **Deploy with config** - Use in async_dispatcher or agent

## Success Criteria

After integration:
- ✓ Configuration loads without errors
- ✓ All values validated on startup
- ✓ Environment-specific config works
- ✓ BeeAI enabled/disabled correctly
- ✓ Fallback works if BeeAI unavailable
- ✓ Fast-fail on invalid configuration
