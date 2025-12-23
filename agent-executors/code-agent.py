#!/usr/bin/env python3
"""
Code LLM Agent

Executes coding tasks autonomously using local code models (Qwen Code, Granite Code).
Reduces human developer load by handling routine code work.

Port: 5001 (to avoid conflict with regular executor on 5000)

Handlers:
  code-generate    → Write new code from specification
  code-refactor    → Improve existing code
  code-test        → Generate unit tests
  code-document    → Add docstrings + comments
  code-fix-lint    → Auto-fix linting errors
"""

import sys
sys.path.insert(0, '/var/home/matt/homelab-config')

from agents.base_agent import AgentExecutor
import logging
import json
import subprocess

logger = logging.getLogger(__name__)


class CodeLLMAgent(AgentExecutor):
    """LLM-powered code agent for autonomous coding tasks"""
    
    EXECUTOR_NAME = "code-agent"
    EXECUTOR_VERSION = "0.1.0"
    
    def __init__(self):
        super().__init__()
        # Initialize Ollama client (optional)
        self.ollama = None
        self.model = None
        try:
            import ollama
            self.ollama = ollama
            # Try to detect available model, default to qwen
            self.model = self._detect_model()
            logger.info(f"Code agent initialized with model: {self.model}")
        except ImportError:
            logger.warning("Ollama library not available; using fallback mode with curl")
            self.model = "qwen2.5-coder:3b"
    
    def _detect_model(self):
        """Detect available code model"""
        try:
            # Try to list models via curl (works even if python ollama library missing)
            result = self.run_command(
                "curl -s http://localhost:11434/api/tags | jq -r '.models[0].name' 2>/dev/null || echo 'qwen2.5-coder:3b'",
                timeout=5
            )
            model = result['output'].strip()
            return model if model else "qwen2.5-coder:3b"
        except Exception:
            return "qwen2.5-coder:3b"
    
    def register_handlers(self):
        """Register code-specific handlers"""
        self.task_handlers = {
            'code-generate': self.handle_code_generate,
            'code-refactor': self.handle_code_refactor,
            'code-test': self.handle_code_test,
            'code-document': self.handle_code_document,
            'code-fix-lint': self.handle_code_fix_lint,
        }
    
    def _ollama_generate(self, prompt: str, temperature: float = 0.7) -> str:
        """Call Ollama for code generation"""
        if self.ollama:
            try:
                response = self.ollama.generate(
                    model=self.model,
                    prompt=prompt,
                    stream=False,
                    options={'temperature': temperature}
                )
                return response.get('response', '')
            except Exception as e:
                logger.error(f"Ollama generate failed: {e}, using curl fallback")
        
        # Fallback: use curl
        escaped_prompt = prompt.replace('"', '\\"').replace('\n', '\\n')
        cmd = f'curl -s http://localhost:11434/api/generate -X POST -d \'{{"model": "{self.model}", "prompt": "{escaped_prompt}", "stream": false}}\' | jq -r ".response"'
        result = self.run_command(cmd, timeout=120)
        return result['output'].strip() if result['success'] else ''
    
    def handle_code_generate(self, params):
        """Generate new code from specification"""
        spec = params.get('spec', '')
        language = params.get('language', 'python')
        
        if not spec:
            return {'output': 'Error: spec required', 'success': False}
        
        prompt = f"""Generate {language} code for this specification:

{spec}

Return only the code, no explanation."""
        
        code = self._ollama_generate(prompt, temperature=0.5)
        
        if not code:
            return {'output': 'Error: Failed to generate code', 'success': False}
        
        # Validate syntax if Python
        validity = 'Unknown'
        if language == 'python':
            try:
                compile(code, '<string>', 'exec')
                validity = 'Valid Python syntax'
            except SyntaxError as e:
                validity = f'Syntax error: {e}'
        
        return {
            'output': code,
            'success': True,
            'language': language,
            'validity': validity,
            'model': self.model
        }
    
    def handle_code_refactor(self, params):
        """Improve code quality, readability, performance"""
        code = params.get('code', '')
        guidance = params.get('guidance', 'improve readability and performance')
        language = params.get('language', 'python')
        
        if not code:
            return {'output': 'Error: code required', 'success': False}
        
        prompt = f"""Refactor this {language} code to {guidance}:

```{language}
{code}
```

Return only the refactored code, no explanation."""
        
        refactored = self._ollama_generate(prompt, temperature=0.5)
        
        if not refactored:
            return {'output': 'Error: Failed to refactor code', 'success': False}
        
        return {
            'output': refactored,
            'success': True,
            'guidance': guidance,
            'language': language,
            'model': self.model
        }
    
    def handle_code_test(self, params):
        """Generate unit tests for code"""
        code = params.get('code', '')
        language = params.get('language', 'python')
        
        if not code:
            return {'output': 'Error: code required', 'success': False}
        
        test_framework = 'pytest' if language == 'python' else 'jest'
        
        prompt = f"""Generate {test_framework} unit tests for this {language} code:

```{language}
{code}
```

Return only the test code, no explanation."""
        
        tests = self._ollama_generate(prompt, temperature=0.3)
        
        if not tests:
            return {'output': 'Error: Failed to generate tests', 'success': False}
        
        return {
            'output': tests,
            'success': True,
            'framework': test_framework,
            'language': language,
            'model': self.model
        }
    
    def handle_code_document(self, params):
        """Add docstrings and comments"""
        code = params.get('code', '')
        language = params.get('language', 'python')
        style = params.get('style', 'google')  # google, numpy, sphinx
        
        if not code:
            return {'output': 'Error: code required', 'success': False}
        
        prompt = f"""Add {style}-style docstrings and helpful comments to this {language} code:

```{language}
{code}
```

Return only the documented code, no explanation."""
        
        documented = self._ollama_generate(prompt, temperature=0.3)
        
        if not documented:
            return {'output': 'Error: Failed to document code', 'success': False}
        
        return {
            'output': documented,
            'success': True,
            'docstring_style': style,
            'language': language,
            'model': self.model
        }
    
    def handle_code_fix_lint(self, params):
        """Auto-fix linting errors"""
        code = params.get('code', '')
        language = params.get('language', 'python')
        linter = params.get('linter', 'flake8')
        
        if not code:
            return {'output': 'Error: code required', 'success': False}
        
        # Run linter to get errors
        errors = 'Linter not configured'
        if language == 'python':
            # Write code to temp file and lint it
            import tempfile
            import os
            
            try:
                with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                    f.write(code)
                    temp_file = f.name
                
                result = self.run_command(f'python3 -m {linter} {temp_file}', timeout=30)
                errors = result['output']
                os.unlink(temp_file)
            except Exception as e:
                errors = f'Linter error: {e}'
        
        prompt = f"""Fix {linter} linting errors in this {language} code:

Code:
```{language}
{code}
```

Errors:
{errors}

Return only the fixed code, no explanation."""
        
        fixed = self._ollama_generate(prompt, temperature=0.3)
        
        if not fixed:
            return {'output': 'Error: Failed to fix linting errors', 'success': False}
        
        return {
            'output': fixed,
            'success': True,
            'linter': linter,
            'errors_found': errors,
            'language': language,
            'model': self.model
        }


if __name__ == '__main__':
    agent = CodeLLMAgent()
    agent.run(host='0.0.0.0', port=5001, debug=False)
