#!/usr/bin/env python3
"""
Yggdrasil Agent - Unified multi-agent system

Goals:
1. Coding assistance (via granite-code)
2. PA tasks (via llama/mistral)
3. Local-first with cloud fallback
4. Beads integration for task tracking
"""

import json
import os
import sys
import time
import logging
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
import urllib.request
import urllib.error

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [Agent] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Try to import BeeAI agents (only available in Python 3.12)
try:
    from beeai_agents import CodeGenerationAgent, TextProcessingAgent, ReasoningAgent
    HAS_BEEAI = True
    logger.info("BeeAI agents available")
except ImportError:
    HAS_BEEAI = False
    logger.info("BeeAI not available (requires Python 3.12)")


class LLMClient:
    """Unified LLM client with router-based host selection and cloud fallback"""
    
    def __init__(self):
        # Load router for host discovery
        from llm_router import LLMRouter
        self.router = LLMRouter()
        self.router.load_config()
        self.router.health_check()
        
        # Cloud fallback
        self.anthropic_key = self._load_anthropic_key()
        self.cloud_model = 'claude-sonnet-4-20250514'
        
    def _load_anthropic_key(self) -> Optional[str]:
        """Load Anthropic API key from environment or crush config"""
        key = os.environ.get('ANTHROPIC_API_KEY')
        if key:
            return key
            
        # Try crush config
        config_path = Path.home() / '.local/share/crush/crush.json'
        if config_path.exists():
            try:
                with open(config_path) as f:
                    config = json.load(f)
                    return config.get('providers', {}).get('anthropic', {}).get('api_key')
            except Exception as e:
                logger.warning(f"Failed to read crush config: {e}")
        return None
    
    def _call_local_llm(self, prompt: str, api_base: str, model: str, system: str = None) -> Optional[str]:
        """Call local LLM via OpenAI-compatible API (ramalama/llama.cpp)"""
        url = f'{api_base}/completions'
        
        # Combine system prompt if provided
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        
        payload = {
            'model': model,
            'prompt': full_prompt,
            'max_tokens': 2048,
            'temperature': 0.7,
        }
            
        try:
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode())
                choices = result.get('choices', [])
                if choices:
                    return choices[0].get('text', '')
                return None
        except Exception as e:
            logger.warning(f"Local LLM call failed: {e}")
            return None
    
    def _call_anthropic(self, prompt: str, system: str = None) -> Optional[str]:
        """Call Anthropic Claude API"""
        if not self.anthropic_key:
            logger.warning("No Anthropic API key available")
            return None
            
        url = 'https://api.anthropic.com/v1/messages'
        
        messages = [{'role': 'user', 'content': prompt}]
        payload = {
            'model': self.cloud_model,
            'max_tokens': 4096,
            'messages': messages,
        }
        if system:
            payload['system'] = system
            
        try:
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={
                'Content-Type': 'application/json',
                'x-api-key': self.anthropic_key,
                'anthropic-version': '2023-06-01'
            })
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode())
                return result.get('content', [{}])[0].get('text', '')
        except Exception as e:
            logger.warning(f"Anthropic call failed: {e}")
            return None
    
    def generate(self, prompt: str, task_type: str = 'general', system: str = None) -> str:
        """Generate response with router-based host selection and cloud fallback"""
        
        # Get best host for this task type
        host = self.router.get_host_for_task(task_type)
        
        if host:
            logger.info(f"Trying {host.name} ({host.model})...")
            result = self._call_local_llm(prompt, host.api_base, host.model, system)
            if result:
                logger.info(f"Local LLM ({host.name}) succeeded")
                return result
            
            # Mark host as unhealthy and try to find another
            host.healthy = False
            host = self.router.get_host_for_task(task_type)
            if host:
                logger.info(f"Trying backup: {host.name} ({host.model})...")
                result = self._call_local_llm(prompt, host.api_base, host.model, system)
                if result:
                    logger.info(f"Backup LLM ({host.name}) succeeded")
                    return result
        
        # Fall back to cloud
        logger.info("Falling back to cloud (Anthropic)...")
        result = self._call_anthropic(prompt, system)
        if result:
            logger.info("Cloud LLM succeeded")
            return result
        
        return "ERROR: All LLM hosts and cloud fallback failed"


class BeadsClient:
    """Read and update Beads tasks"""
    
    def __init__(self, beads_dir: str = None):
        if beads_dir:
            self.beads_dir = Path(beads_dir)
        else:
            # Try common locations (container, then local)
            for path in [
                Path('/beads'),  # Container mount
                Path('/vault'),  # Container mount
                Path.home() / 'homelab-config/yggdrasil-beads',
                Path.cwd(),
            ]:
                if (path / '.beads/issues.jsonl').exists():
                    self.beads_dir = path
                    break
            else:
                raise FileNotFoundError("Could not find Beads directory")
        
        self.issues_file = self.beads_dir / '.beads/issues.jsonl'
        logger.info(f"Using Beads at: {self.beads_dir}")
    
    def get_ready_tasks(self) -> List[Dict[str, Any]]:
        """Get tasks that are open and ready to work"""
        tasks = []
        with open(self.issues_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    task = json.loads(line)
                    if task.get('status') == 'open' and task.get('issue_type') != 'epic':
                        tasks.append(task)
                except json.JSONDecodeError:
                    continue
        return tasks
    
    def update_task(self, task_id: str, status: str, result: str = None):
        """Update task status in Beads"""
        lines = []
        with open(self.issues_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    task = json.loads(line)
                    if task['id'] == task_id:
                        task['status'] = status
                        task['updated_at'] = datetime.now(timezone.utc).isoformat()
                        if status == 'closed':
                            task['closed_at'] = datetime.now(timezone.utc).isoformat()
                        if result:
                            task['result'] = result[:1000]  # Truncate long results
                    lines.append(json.dumps(task))
                except json.JSONDecodeError:
                    lines.append(line)
        
        with open(self.issues_file, 'w') as f:
            for line in lines:
                f.write(line + '\n')
        
        logger.info(f"Updated task {task_id} to {status}")


class YggdrasilAgent:
    """Main agent that processes tasks from Beads"""
    
    def __init__(self):
        self.llm = LLMClient()
        self.beads = BeadsClient()
        self.use_beeai = HAS_BEEAI
        
        # Initialize BeeAI agents if available
        if self.use_beeai:
            self._init_beeai_agents()
        
        # Task type handlers (use BeeAI if available, else fallback to simple LLM)
        self.handlers = {
            'code-generation': self._handle_code_generation,
            'text-processing': self._handle_text_processing,
            'reasoning': self._handle_reasoning,
            'summarize': self._handle_summarize,
            'general': self._handle_general,
        }
    
    def _init_beeai_agents(self):
        """Initialize BeeAI agents with task-specific LLM routing"""
        try:
            from beeai_framework.backend import ChatModel
            import os
            
            # Cloud fallback: Anthropic (requires API key)
            self.cloud_llm = None
            if self.llm.anthropic_key:
                try:
                    os.environ['ANTHROPIC_API_KEY'] = self.llm.anthropic_key
                    self.cloud_llm = ChatModel.from_name('anthropic:claude-sonnet-4-20250514')
                except Exception as e:
                    logger.warning(f"Failed to initialize Anthropic: {e}")
            
            # Create task-specific agents with appropriate LLM hosts
            # Code agent -> surtr-code (granite-code)
            code_host = self.llm.router.get_host_for_task('code-generation')
            if code_host:
                os.environ['OLLAMA_API_BASE'] = code_host.api_base
                code_llm = ChatModel.from_name(f'ollama:{code_host.model}')
                self.code_agent = CodeGenerationAgent(code_llm, self.cloud_llm)
                logger.info(f"Code agent using {code_host.name} ({code_host.model})")
            else:
                self.code_agent = None
            
            # Reasoning agent -> surtr-reasoning (gpt-oss) 
            reasoning_host = self.llm.router.get_host_for_task('reasoning')
            if reasoning_host:
                os.environ['OLLAMA_API_BASE'] = reasoning_host.api_base
                reasoning_llm = ChatModel.from_name(f'ollama:{reasoning_host.model}')
                self.reasoning_agent = ReasoningAgent(reasoning_llm, self.cloud_llm)
                logger.info(f"Reasoning agent using {reasoning_host.name} ({reasoning_host.model})")
            else:
                self.reasoning_agent = None
            
            # Text agent -> fenrir-chat (qwen)
            text_host = self.llm.router.get_host_for_task('text-processing')
            if text_host:
                os.environ['OLLAMA_API_BASE'] = text_host.api_base
                text_llm = ChatModel.from_name(f'ollama:{text_host.model}')
                self.text_agent = TextProcessingAgent(text_llm, self.cloud_llm)
                logger.info(f"Text agent using {text_host.name} ({text_host.model})")
            else:
                self.text_agent = None
            
            logger.info("BeeAI agents initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize BeeAI agents: {e}")
            self.use_beeai = False
    
    def _detect_task_type(self, task: Dict[str, Any]) -> str:
        """Detect task type from labels or title"""
        labels = task.get('labels', [])
        title = task.get('title', '').lower()
        
        if 'code-generation' in labels or title.startswith('code task:'):
            return 'code-generation'
        if 'text-processing' in labels or 'summarize' in title:
            return 'text-processing'
        if 'reasoning' in labels or 'analyze' in title or 'explain' in title:
            return 'reasoning'
        if 'summarize' in title:
            return 'summarize'
        
        return 'general'
    
    def _handle_code_generation(self, task: Dict[str, Any]) -> str:
        """Generate code based on task description"""
        description = task.get('description', '')
        title = task.get('title', '')
        
        # Use BeeAI if available
        if self.use_beeai and self.code_agent:
            try:
                prompt = f"""Generate code for the following task:

Title: {title}
Description: {description}

Provide complete, working code with comments. Include any necessary imports.
Use the write_file tool to save the code to an appropriate location."""
                
                result = asyncio.run(self.code_agent.process(prompt))
                return result
            except Exception as e:
                logger.warning(f"BeeAI code generation failed: {e}, falling back to simple LLM")
        
        # Fallback to simple LLM
        prompt = f"""Generate code for the following task:

Title: {title}
Description: {description}

Provide complete, working code with comments. Include any necessary imports."""
        
        return self.llm.generate(prompt, task_type='code')
    
    def _handle_text_processing(self, task: Dict[str, Any]) -> str:
        """Process text (summarize, extract, rewrite, etc.)"""
        description = task.get('description', '')
        title = task.get('title', '')
        
        # Use BeeAI if available
        if self.use_beeai and self.text_agent:
            try:
                prompt = f"""Task: {title}

{description}

Use tools as needed to read input files or write results."""
                
                result = asyncio.run(self.text_agent.process(prompt))
                return result
            except Exception as e:
                logger.warning(f"BeeAI text processing failed: {e}, falling back to simple LLM")
        
        # Fallback to simple LLM
        prompt = description
        return self.llm.generate(prompt, task_type='text')
    
    def _handle_summarize(self, task: Dict[str, Any]) -> str:
        """Summarize content"""
        description = task.get('description', '')
        
        # Use BeeAI if available
        if self.use_beeai and self.reasoning_agent:
            try:
                prompt = f"Please summarize the following:\n\n{description}"
                result = asyncio.run(self.reasoning_agent.process(prompt))
                return result
            except Exception as e:
                logger.warning(f"BeeAI summarization failed: {e}, falling back to simple LLM")
        
        # Fallback to simple LLM
        prompt = f"Please summarize the following:\n\n{description}"
        return self.llm.generate(prompt, task_type='text')
    
    def _handle_reasoning(self, task: Dict[str, Any]) -> str:
        """Handle complex reasoning tasks"""
        description = task.get('description', '')
        title = task.get('title', '')
        
        # Use BeeAI if available
        if self.use_beeai and self.reasoning_agent:
            try:
                prompt = f"""Task: {title}

{description}

Provide thorough analysis and reasoning."""
                
                result = asyncio.run(self.reasoning_agent.process(prompt))
                return result
            except Exception as e:
                logger.warning(f"BeeAI reasoning failed: {e}, falling back to simple LLM")
        
        # Fallback to simple LLM
        prompt = f"""Task: {title}

{description}

Please analyze this thoroughly and provide clear reasoning."""
        
        return self.llm.generate(prompt, task_type='general')
    
    def _handle_general(self, task: Dict[str, Any]) -> str:
        """Handle general tasks"""
        description = task.get('description', '')
        title = task.get('title', '')
        
        # Use BeeAI if available and has agents
        if self.use_beeai and self.reasoning_agent:
            try:
                prompt = f"""Task: {title}

{description}

Please complete this task and provide a clear response."""
                
                result = asyncio.run(self.reasoning_agent.process(prompt))
                return result
            except Exception as e:
                logger.warning(f"BeeAI general handling failed: {e}, falling back to simple LLM")
        
        # Fallback to simple LLM
        prompt = f"""Task: {title}

{description}

Please complete this task and provide a clear response."""

        return self.llm.generate(prompt, task_type='general')
    
    def process_task(self, task: Dict[str, Any]) -> str:
        """Process a single task"""
        task_id = task.get('id')
        task_type = self._detect_task_type(task)
        
        logger.info(f"Processing {task_id} (type: {task_type})")
        
        # Mark as in-progress
        self.beads.update_task(task_id, 'in_progress')
        
        try:
            # Get handler
            handler = self.handlers.get(task_type, self._handle_general)
            result = handler(task)
            
            # Ensure result is a string
            result_str = str(result) if not isinstance(result, str) else result
            
            # Mark as completed
            self.beads.update_task(task_id, 'closed', result_str)
            
            return result_str
            
        except Exception as e:
            logger.error(f"Task failed: {e}")
            self.beads.update_task(task_id, 'blocked', str(e))
            return f"ERROR: {e}"
    
    def run_once(self) -> bool:
        """Process one ready task. Returns True if a task was processed."""
        tasks = self.beads.get_ready_tasks()
        
        if not tasks:
            logger.info("No ready tasks")
            return False
        
        task = tasks[0]
        self.process_task(task)
        return True
    
    def run_loop(self, poll_interval: int = 30):
        """Continuously poll for and process tasks"""
        logger.info("Starting agent loop...")
        
        while True:
            try:
                if not self.run_once():
                    time.sleep(poll_interval)
                else:
                    time.sleep(5)  # Brief pause between tasks
            except KeyboardInterrupt:
                logger.info("Agent stopped")
                break
            except Exception as e:
                logger.exception(f"Error in agent loop: {e}")
                time.sleep(poll_interval)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Yggdrasil Agent')
    parser.add_argument('--once', action='store_true', help='Process one task and exit')
    parser.add_argument('--beads', type=str, help='Path to Beads directory')
    args = parser.parse_args()
    
    agent = YggdrasilAgent()
    
    if args.once:
        agent.run_once()
    else:
        agent.run_loop()


if __name__ == '__main__':
    main()
