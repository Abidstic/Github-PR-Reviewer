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
                "HTTP-Referer": "https://github.com/reviewer-ai",
                "X-Title": "GitHub Reviewer AI"
            }
        )
        
        logger.info(f"✅ LLM client initialized (model: {self.model} via OpenRouter)")

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
            # Use direct OpenAI completion call
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt_text}],
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            
            response = completion.choices[0].message.content
            
            elapsed = time.time() - start_time
            logger.debug(f"✅ LLM response generated in {elapsed:.2f}s")
            
            return self._extract_json(response) if parse_json else response
            
        except Exception as e:
            logger.error(f"❌ LLM generation failed: {e}")
            raise

    def _extract_json(self, text: str) -> Dict:
        """Extract JSON safely from LLM text"""
        import re
        
        # 1. Try to find JSON block using markdown indicators
        json_match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
        if json_match:
            try:
                content = json_match.group(1).strip()
                return json.loads(content)
            except json.JSONDecodeError:
                # If markdown content is not valid JSON, fall through to other methods
                pass

        # 2. Try finding the outermost brackets
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            json_str = text[start:end+1]
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                # If greedy match fails, try smaller potential JSON objects
                # (less robust but might catch something)
                pass

        # 3. Last resort: regex search for anything between braces
        # using a non-greedy approach for potentially multiple objects
        brace_matches = re.finditer(r'\{.*?\}', text, re.DOTALL)
        for match in brace_matches:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                continue

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