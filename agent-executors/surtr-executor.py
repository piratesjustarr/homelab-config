#!/usr/bin/env python3
"""
Surtr Executor (LLM Agent)

Handles Ollama deployment, model management, inference tasks.
Runs on: surtr.nessie-hippocampus.ts.net:5000
"""

import sys
sys.path.insert(0, '/var/home/matt/homelab-config')

from agents.base_agent import AgentExecutor
import logging

logger = logging.getLogger(__name__)


class SurtrExecutor(AgentExecutor):
    """LLM agent for Ollama deployment, inference, model management"""
    
    EXECUTOR_NAME = "surtr-executor"
    EXECUTOR_VERSION = "0.1.0"
    
    def register_handlers(self):
        """Register task handlers for Surtr"""
        
        self.task_handlers = {
            'llm-health-check': self.handle_health_check,
            'ollama-deploy': self.handle_ollama_deploy,
            'ollama-pull-model': self.handle_ollama_pull_model,
            'ollama-list-models': self.handle_ollama_list_models,
            'llm-inference': self.handle_llm_inference,
            'gpu-verify': self.handle_gpu_verify,
        }
    
    def handle_health_check(self, params):
        """Verify Surtr is operational"""
        result = self.run_command('uname -a && nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo "GPU not available"')
        return {
            'output': f"Surtr health check:\n{result['output']}"
        }
    
    def handle_ollama_deploy(self, params):
        """Deploy Ollama via docker-compose"""
        # Using existing docker-compose in homelab directory
        cmd = 'cd ~/homelab && docker-compose up -d ollama && sleep 5 && curl http://localhost:11434/api/tags'
        result = self.run_command(cmd, timeout=300)
        
        return {
            'output': result['output'],
            'success': result['success']
        }
    
    def handle_ollama_pull_model(self, params):
        """Pull an LLM model into Ollama"""
        model_name = params.get('model', 'llama3.1:8b')
        
        cmd = f"ollama pull {model_name}"
        result = self.run_command(cmd, timeout=600)  # Long timeout for large models
        
        return {
            'output': result['output'],
            'success': result['success']
        }
    
    def handle_ollama_list_models(self, params):
        """List available models in Ollama"""
        cmd = "curl -s http://localhost:11434/api/tags | jq ."
        result = self.run_command(cmd, timeout=10)
        
        return {
            'output': result['output'],
            'success': result['success']
        }
    
    def handle_llm_inference(self, params):
        """Run inference against local model"""
        model = params.get('model', 'llama3.1:8b')
        prompt = params.get('prompt', 'Hello')
        
        cmd = f'curl -s -X POST http://localhost:11434/api/generate -d \'{{"model": "{model}", "prompt": "{prompt}"}}\' | jq .'
        result = self.run_command(cmd, timeout=120)
        
        return {
            'output': result['output'],
            'success': result['success']
        }
    
    def handle_gpu_verify(self, params):
        """Verify GPU access and CUDA"""
        cmd = "nvidia-smi && python3 -c 'import torch; print(f\"CUDA available: {torch.cuda.is_available()}\")' 2>/dev/null || echo 'PyTorch not available'"
        result = self.run_command(cmd, timeout=30)
        
        return {
            'output': result['output'],
            'success': result['success']
        }


if __name__ == '__main__':
    agent = SurtrExecutor()
    agent.run(host='0.0.0.0', port=5000, debug=False)
