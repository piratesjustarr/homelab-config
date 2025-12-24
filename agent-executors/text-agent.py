#!/usr/bin/env python3

import sys
import os
sys.path.insert(0, '/app')

from agents.base_agent import AgentExecutor
import logging
import json
import subprocess

"""
Text LLM Agent

Executes text processing tasks autonomously using local language models (Llama, Mistral).
Handles summarization, extraction, classification, rewriting, and analysis.

Port: 5002 (to avoid conflict with code-agent on 5001, executor on 5000)

Handlers:
  text-summarize   → Summarize documents/text
  text-extract     → Extract structured information
  text-classify    → Classify/categorize text
  text-rewrite     → Improve/rewrite text
  text-analyze     → Analyze sentiment/content/themes
"""

logger = logging.getLogger(__name__)


class TextLLMAgent(AgentExecutor):
    """LLM-powered text processing agent for autonomous text tasks"""
    
    EXECUTOR_NAME = "text-agent"
    EXECUTOR_VERSION = "0.1.0"
    
    def __init__(self):
        super().__init__()
        # LLM endpoint config
        self.llm_host = os.environ.get('LLM_HOST', 'localhost:8131')
        self.model = os.environ.get('LLM_MODEL', 'llama3.2:3b')
        logger.info(f"Text agent initialized: {self.llm_host} / {self.model}")
    
    def _llm_generate(self, prompt: str, temperature: float = 0.7) -> str:
        """Call LLM (ramalama/ollama) for text processing using OpenAI-compatible API"""
        import requests
        
        url = f"http://{self.llm_host}/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "stream": False
        }
        
        try:
            response = requests.post(url, json=payload, timeout=300)
            response.raise_for_status()
            data = response.json()
            return data.get('choices', [{}])[0].get('message', {}).get('content', '')
        except Exception as e:
            logger.error(f"LLM request failed: {e}")
            return ''

    def register_handlers(self):
        """Register text-specific handlers"""
        self.task_handlers = {
            'text-summarize': self.handle_text_summarize,
            'text-extract': self.handle_text_extract,
            'text-classify': self.handle_text_classify,
            'text-rewrite': self.handle_text_rewrite,
            'text-analyze': self.handle_text_analyze,
        }
    
    def handle_text_summarize(self, params):
        """Summarize text or document"""
        text = params.get('text', '')
        style = params.get('style', 'concise')  # concise, bullet, detailed
        max_length = params.get('max_length', 500)
        
        if not text:
            return {'output': 'Error: text required', 'success': False}
        
        style_guide = {
            'concise': 'Create a brief, one-paragraph summary',
            'bullet': 'Create a bullet-point summary with key points',
            'detailed': 'Create a detailed summary preserving important nuances'
        }
        
        prompt = f"""You are a skilled technical writer and summarizer. {style_guide.get(style, style_guide['concise'])}.

Text to summarize:
{text}

Guidelines:
- Preserve key information and context
- Write clearly and concisely
- Focus on main ideas and conclusions
- Keep under {max_length} characters if possible
- Do not add information not in original text

Summary:"""
        
        summary = self._llm_generate(prompt, temperature=0.3)
        return {
            'output': summary,
            'success': bool(summary),
            'task_id': params.get('task_id'),
            'status': 'completed'
        }
    
    def handle_text_extract(self, params):
        """Extract structured information from text"""
        text = params.get('text', '')
        extraction_type = params.get('extraction_type', 'entities')  # entities, facts, contact_info, etc
        format_type = params.get('format', 'json')  # json, list, table
        
        if not text:
            return {'output': 'Error: text required', 'success': False}
        
        extraction_prompts = {
            'entities': 'Extract named entities (people, places, organizations, dates)',
            'facts': 'Extract factual statements and claims',
            'contact_info': 'Extract contact information (emails, phone numbers, addresses)',
            'keywords': 'Extract key terms and keywords'
        }
        
        prompt = f"""You are an information extraction expert. {extraction_prompts.get(extraction_type, extraction_prompts['entities'])}.

Text:
{text}

Guidelines:
- Extract only information explicitly in the text
- Format as {format_type}
- Be comprehensive but accurate
- Return only the extracted information

Extracted information:"""
        
        extracted = self._llm_generate(prompt, temperature=0.1)
        return {
            'output': extracted,
            'success': bool(extracted),
            'task_id': params.get('task_id'),
            'status': 'completed'
        }
    
    def handle_text_classify(self, params):
        """Classify or categorize text"""
        text = params.get('text', '')
        classification_type = params.get('classification_type', 'sentiment')  # sentiment, topic, urgency, etc
        categories = params.get('categories', [])
        
        if not text:
            return {'output': 'Error: text required', 'success': False}
        
        classification_guides = {
            'sentiment': 'Classify sentiment as: positive, negative, or neutral',
            'topic': f'Classify into one of these categories: {", ".join(categories)}',
            'urgency': 'Classify urgency level as: low, medium, high, or critical',
            'toxicity': 'Assess if text contains toxic/harmful content: yes or no'
        }
        
        guide = classification_guides.get(classification_type, classification_guides['sentiment'])
        
        prompt = f"""You are a text classification expert. {guide}.

Text:
{text}

Guidelines:
- Provide a clear classification
- Explain your reasoning briefly (1-2 sentences)
- Be objective and consistent

Classification:"""
        
        classification = self._llm_generate(prompt, temperature=0.2)
        return {
            'output': classification,
            'success': bool(classification),
            'task_id': params.get('task_id'),
            'status': 'completed'
        }
    
    def handle_text_rewrite(self, params):
        """Rewrite or improve text"""
        text = params.get('text', '')
        style = params.get('style', 'improve')  # improve, formal, casual, technical, simple, creative
        tone = params.get('tone', 'neutral')  # neutral, professional, friendly, assertive
        
        if not text:
            return {'output': 'Error: text required', 'success': False}
        
        style_descriptions = {
            'improve': 'Improve clarity, grammar, and readability',
            'formal': 'Rewrite in formal, professional tone',
            'casual': 'Rewrite in casual, conversational tone',
            'technical': 'Rewrite with technical terminology and precision',
            'simple': 'Simplify to explain to a general audience',
            'creative': 'Rewrite in creative, engaging style'
        }
        
        prompt = f"""You are a skilled editor and writer. {style_descriptions.get(style, style_descriptions['improve'])}. Maintain a {tone} tone.

Original text:
{text}

Guidelines:
- Preserve the original meaning and intent
- Improve where possible without changing content
- Maintain the same length approximately
- Return only the rewritten text

Rewritten text:"""
        
        rewritten = self._llm_generate(prompt, temperature=0.6)
        return {
            'output': rewritten,
            'success': bool(rewritten),
            'task_id': params.get('task_id'),
            'status': 'completed'
        }
    
    def handle_text_analyze(self, params):
        """Analyze text for themes, patterns, sentiment, etc"""
        text = params.get('text', '')
        analysis_type = params.get('analysis_type', 'general')  # general, sentiment, themes, reasoning, structure
        
        if not text:
            return {'output': 'Error: text required', 'success': False}
        
        analysis_prompts = {
            'general': 'Provide a comprehensive analysis of this text, covering its main points, structure, and tone',
            'sentiment': 'Analyze the emotional tone and sentiment throughout the text',
            'themes': 'Identify and analyze the main themes and concepts',
            'reasoning': 'Analyze the logical arguments and reasoning presented',
            'structure': 'Analyze how the text is structured and organized'
        }
        
        prompt = f"""You are a text analysis expert. {analysis_prompts.get(analysis_type, analysis_prompts['general'])}.

Text:
{text}

Guidelines:
- Provide detailed, insightful analysis
- Use specific examples from the text
- Be objective and thorough
- Organize findings clearly

Analysis:"""
        
        analysis = self._llm_generate(prompt, temperature=0.5)
        return {
            'output': analysis,
            'success': bool(analysis),
            'task_id': params.get('task_id'),
            'status': 'completed'
        }


if __name__ == '__main__':
    agent = TextLLMAgent()
    agent.start(port=5002)
