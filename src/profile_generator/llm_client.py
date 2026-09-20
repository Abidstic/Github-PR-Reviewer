"""
LLM Client
Wrapper for LLM API calls (Qwen via OpenRouter) - Modern LCEL Version
"""

import os
import json
import time
from typing import Dict, Optional, Any
from pathlib import Path

from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable

from src.utils import get_logger, get_config, retry_on_failure

logger = get_logger(__name__)


class LLMClient:
    """Client for LLM API interactions using LCEL"""
    
    def __init__(self, api_key: Optional[str] = None, api_base: Optional[str] = None):
        """Initialize LLM client with modern parameters"""
        self.config = get_config()
        
        # Get API credentials
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        self.api_base = api_base or os.getenv('OPENAI_API_BASE', 'https://openrouter.ai/api/v1')
        
        if not self.api_key:
            raise ValueError("OpenRouter API key missing. Set OPENAI_API_KEY in .env")
        
        # Get LLM settings
        self.model = self.config.get('llm.model', 'qwen/qwen-2.5-72b-instruct')
        self.temperature = self.config.get('llm.temperature', 0.3)
        self.max_tokens = self.config.get('llm.max_tokens', 4000)

        # We'll use the OpenAI client directly for stability with OpenRouter
        # This avoids the "proxies" error in older LangChain versions
        from openai import OpenAI
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.api_base,
            default_headers={
                "HTTP-Referer": "https://github.com/apps/reviewermatch",
                "X-Title": "ReviewerMatch"
            }
        )
        
        logger.info(f"✅ LLM client initialized (model: {self.model} via {self.api_base})")

    def load_prompt_template(self, template_name: str) -> str:
        """Load prompt template from file"""
        template_path = Path('config/prompts') / template_name
        if not template_path.exists():
            raise FileNotFoundError(f"Prompt template not found: {template_path}")
        
        with open(template_path, 'r', encoding='utf-8') as f:
            return f.read()

    @retry_on_failure(max_attempts=3, delay=2.0, backoff=2.0)
    def generate(
        self,
        prompt_template: str,
        variables: Dict[str, Any],
        parse_json: bool = False
    ) -> Any:
        """Generate completion using direct OpenAI client for maximum stability"""
        # Load template if it's a file path
        if not '\n' in prompt_template and prompt_template.endswith('.txt'):
            prompt_template = self.load_prompt_template(prompt_template)
        
        # Format the prompt with variables
        try:
            prompt_text = prompt_template.format(**variables)
        except KeyError as e:
            logger.error(f"❌ Missing variable in prompt template: {e}")
            raise
        
        logger.debug(f"🤖 Generating LLM response for {self.model}...")
        start_time = time.time()
        
        try:
            kwargs = dict(
                model=self.model,
                messages=[{"role": "user", "content": prompt_text}],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            # OpenRouter-specific provider routing (ignored by other APIs)
            if 'openrouter.ai' in self.api_base:
                ignore_providers = self.config.get('llm.ignore_providers', ['Novita'])
                if ignore_providers:
                    kwargs['extra_body'] = {"provider": {"ignore": ignore_providers}}

            completion = self.client.chat.completions.create(**kwargs)
            
            response = completion.choices[0].message.content
            
            elapsed = time.time() - start_time
            logger.debug(f"✅ LLM response generated in {elapsed:.2f}s")
            
            return self._extract_json(response) if parse_json else response
            
        except Exception as e:
            logger.error(f"❌ LLM generation failed: {e}")
            raise

    @staticmethod
    def _clean_json_string(text: str) -> str:
        """Strip JS-style comments and fix multi-line strings for JSON parsing."""
        import re
        lines = text.split('\n')
        cleaned = []
        for line in lines:
            stripped = line.rstrip()
            # Remove trailing // comments (but not inside quoted strings)
            # Find // that isn't inside a quoted value
            in_string = False
            escape_next = False
            comment_start = -1
            for i, ch in enumerate(stripped):
                if escape_next:
                    escape_next = False
                    continue
                if ch == '\\':
                    escape_next = True
                    continue
                if ch == '"':
                    in_string = not in_string
                elif not in_string and ch == '/' and i + 1 < len(stripped) and stripped[i + 1] == '/':
                    comment_start = i
                    break
            if comment_start >= 0:
                stripped = stripped[:comment_start].rstrip()
                # Remove trailing comma left before a comment on the same line
                if stripped.endswith(',') and not stripped.endswith('",'):
                    pass  # trailing comma is fine if next line has content
            cleaned.append(stripped)

        result = '\n'.join(cleaned)

        # Collapse multi-line string values: replace unescaped newlines inside
        # JSON string values with a space
        def _fix_multiline_strings(m: re.Match) -> str:
            val = m.group(0)
            inner = val[1:-1]  # strip surrounding quotes
            inner = inner.replace('\n', ' ').replace('\r', '')
            inner = re.sub(r'\s{2,}', ' ', inner)
            return '"' + inner + '"'

        result = re.sub(r'"(?:[^"\\]|\\.)*"', _fix_multiline_strings, result, flags=re.DOTALL)
        return result

    def _extract_json(self, text: str) -> Dict:
        """Extract JSON safely from LLM text"""
        import re

        candidates = []

        # 1. Try to find JSON block using markdown indicators
        json_match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
        if json_match:
            candidates.append(json_match.group(1).strip())

        # 2. Try finding the outermost brackets
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            candidates.append(text[start:end+1])

        for raw in candidates:
            # Try raw first
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
            # Try after cleaning comments and multi-line strings
            try:
                cleaned = self._clean_json_string(raw)
                return json.loads(cleaned)
            except (json.JSONDecodeError, ValueError):
                pass

        # If all else fails
        logger.error(f"❌ Failed to extract JSON from response. Raw text:\n{text}")
        raise ValueError("No valid JSON object found in LLM response")



# Example usage and testing
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    print("🤖 Testing LLM Client")
    print("=" * 60)
    
    # Initialize client
    try:
        client = LLMClient()
        print("✅ LLM client initialized successfully!")
        
        # Test simple generation with proper variables
        print("\n📝 Testing simple generation...")
        simple_template = "What are the top 3 {language} frameworks? Answer in one sentence."
        response = client.generate(simple_template, {"language": "JavaScript"})
        print(f"✅ Response: {response[:150]}...")
        
        print("\n✅ LLM client working correctly!")
        
    except ValueError as e:
        print(f"⚠️ Configuration error: {e}")
        print("Make sure OPENAI_API_KEY is set in .env file")
    except Exception as e:
        print(f"❌ Error: {e}")