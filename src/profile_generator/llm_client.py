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
        api_key = api_key or os.getenv('OPENAI_API_KEY')
        api_base = api_base or os.getenv('OPENAI_API_BASE', 'https://openrouter.ai/api/v1')
        
        if not api_key:
            raise ValueError("OpenRouter API key missing. Set OPENAI_API_KEY in .env")
        
        # Get LLM settings
        model = self.config.get('llm.model', 'qwen/qwen-2.5-72b-instruct')
        temperature = self.config.get('llm.temperature', 0.3)
        max_tokens = self.config.get('llm.max_tokens', 4000)
        
        # Initialize modern ChatOpenAI client
        self.llm = ChatOpenAI(
            model=model,  
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=api_key,
            base_url=api_base,
            default_headers={"HTTP-Referer": "https://github.com/reviewer-ai", "X-Title": "GitHub Reviewer AI"}
        )
        
        logger.info(f"✅ LLM client initialized (model: {model})")

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
        """Generate completion using LCEL pipe syntax"""
        # Load template if it's a file path
        if not '\n' in prompt_template and prompt_template.endswith('.txt'):
            prompt_template = self.load_prompt_template(prompt_template)
        
        # Build the chain: Prompt -> LLM -> String Output
        prompt = PromptTemplate.from_template(prompt_template)
        chain = prompt | self.llm | StrOutputParser()
        
        logger.debug("🤖 Generating LLM response...")
        start_time = time.time()
        
        try:
            # invoke() is the modern replacement for run()
            response = chain.invoke(variables)
            
            elapsed = time.time() - start_time
            logger.debug(f"✅ LLM response generated in {elapsed:.2f}s")
            
            return self._extract_json(response) if parse_json else response
            
        except Exception as e:
            logger.error(f"❌ LLM generation failed: {e}")
            raise

    def create_chain(self, prompt_template: str) -> Runnable:
        """Create a reusable LCEL Runnable"""
        if not '\n' in prompt_template and prompt_template.endswith('.txt'):
            prompt_template = self.load_prompt_template(prompt_template)
        
        prompt = PromptTemplate.from_template(prompt_template)
        return prompt | self.llm | StrOutputParser()

    def _extract_json(self, text: str) -> Dict:
        """Extract JSON safely from LLM text"""
        import re
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON object found in response")
        
        json_str = json_match.group().replace('```json', '').replace('```', '').strip()
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON Parse Error: {e}")
            raise


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