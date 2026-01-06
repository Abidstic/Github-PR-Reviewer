"""
LLM Client
Wrapper for LLM API calls (Qwen via OpenRouter)
"""

import os
import json
import time
from typing import Dict, Optional, Any
from pathlib import Path

from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain.chains import LLMChain

from src.utils import get_logger, get_config, retry_on_failure

logger = get_logger(__name__)


class LLMClient:
    """Client for LLM API interactions"""
    
    def __init__(self, api_key: Optional[str] = None, api_base: Optional[str] = None):
        """
        Initialize LLM client
        
        Args:
            api_key: OpenRouter API key (from .env if not provided)
            api_base: API base URL (from .env if not provided)
        """
        self.config = get_config()
        
        # Get API credentials
        if api_key is None:
            api_key = os.getenv('OPENAI_API_KEY')
        if api_base is None:
            api_base = os.getenv('OPENAI_API_BASE', 'https://openrouter.ai/api/v1')
        
        if not api_key:
            raise ValueError(
                "OpenRouter API key not provided. "
                "Set OPENAI_API_KEY in .env or pass api_key parameter"
            )
        
        # Get LLM settings from config
        model = self.config.get('llm.model', 'qwen/qwen-2.5-72b-instruct')
        temperature = self.config.get('llm.temperature', 0.3)
        max_tokens = self.config.get('llm.max_tokens', 4000)
        
        # Initialize LangChain ChatOpenAI
        self.llm = ChatOpenAI(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            openai_api_key=api_key,
            openai_api_base=api_base
        )
        
        # Retry settings
        self.max_retries = self.config.get('llm.retry_attempts', 3)
        self.retry_delay = self.config.get('llm.retry_delay', 2)
        
        logger.info(f"✅ LLM client initialized (model: {model})")
    
    def load_prompt_template(self, template_name: str) -> str:
        """
        Load prompt template from file
        
        Args:
            template_name: Template filename (without path)
        
        Returns:
            Template content as string
        """
        template_path = Path('config/prompts') / template_name
        
        if not template_path.exists():
            raise FileNotFoundError(f"Prompt template not found: {template_path}")
        
        with open(template_path, 'r', encoding='utf-8') as f:
            template = f.read()
        
        logger.debug(f"📄 Loaded prompt template: {template_name}")
        return template
    
    @retry_on_failure(max_attempts=3, delay=2.0, backoff=2.0)
    def generate(
        self,
        prompt_template: str,
        variables: Dict[str, Any],
        parse_json: bool = False
    ) -> str:
        """
        Generate completion from LLM
        
        Args:
            prompt_template: Prompt template string or path to template file
            variables: Variables to fill in template
            parse_json: Whether to extract and parse JSON from response
        
        Returns:
            LLM response (raw text or parsed JSON)
        """
        # Check if prompt_template is a file path
        if not '\n' in prompt_template and prompt_template.endswith('.txt'):
            prompt_template = self.load_prompt_template(prompt_template)
        
        # Create prompt
        prompt = PromptTemplate(
            input_variables=list(variables.keys()),
            template=prompt_template
        )
        
        # Create chain
        chain = LLMChain(llm=self.llm, prompt=prompt, verbose=False)
        
        # Generate response
        logger.debug("🤖 Generating LLM response...")
        start_time = time.time()
        
        try:
            response = chain.run(**variables)
            
            elapsed = time.time() - start_time
            logger.debug(f"✅ LLM response generated in {elapsed:.2f}s")
            
            # Parse JSON if requested
            if parse_json:
                return self._extract_json(response)
            
            return response
            
        except Exception as e:
            logger.error(f"❌ LLM generation failed: {e}")
            raise
    
    def _extract_json(self, text: str) -> Dict:
        """
        Extract JSON object from LLM response
        
        Args:
            text: LLM response text
        
        Returns:
            Parsed JSON dictionary
        """
        import re
        
        # Try to find JSON block
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        
        if not json_match:
            raise ValueError("No JSON object found in LLM response")
        
        json_str = json_match.group()
        
        # Remove markdown code blocks if present
        json_str = json_str.replace('```json', '').replace('```', '').strip()
        
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse JSON from LLM response: {e}")
            logger.debug(f"Raw JSON string: {json_str[:500]}...")
            raise
    
    def create_chain(self, prompt_template: str) -> LLMChain:
        """
        Create a reusable LLMChain
        
        Args:
            prompt_template: Prompt template string or path to template file
        
        Returns:
            LLMChain instance
        """
        # Load template if it's a file path
        if not '\n' in prompt_template and prompt_template.endswith('.txt'):
            prompt_template = self.load_prompt_template(prompt_template)
        
        # Extract variables from template
        import re
        variables = re.findall(r'\{(\w+)\}', prompt_template)
        
        # Create prompt
        prompt = PromptTemplate(
            input_variables=list(set(variables)),
            template=prompt_template
        )
        
        # Create chain
        chain = LLMChain(llm=self.llm, prompt=prompt, verbose=False)
        
        return chain


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