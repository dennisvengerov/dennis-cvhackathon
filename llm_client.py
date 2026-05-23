import os
import sys
import re
import json
from typing import Optional, Any
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Load environmental variables
load_dotenv()

_client_instance = None

def get_gemini_client() -> Optional[genai.Client]:
    """
    Initializes and returns the Google GenAI client if GEMINI_API_KEY is configured.
    """
    global _client_instance
    if _client_instance is not None:
        return _client_instance
        
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
        
    try:
        # Client automatically picks up GEMINI_API_KEY from environment
        _client_instance = genai.Client()
        return _client_instance
    except Exception as e:
        print(f"Warning: Failed to initialize Google GenAI client: {e}", file=sys.stderr)
        return None

def generate_content(
    prompt: str,
    model: str = "gemini-2.5-flash",
    no_llm: bool = False,
    json_mode: bool = False
) -> Optional[str]:
    """
    Queries Gemini API to generate content with the given prompt.
    Returns None if no_llm is True, the client is unconfigured, or the call fails.
    """
    if no_llm:
        return None
        
    client = get_gemini_client()
    if not client:
        return None
        
    try:
        config = None
        if json_mode:
            config = types.GenerateContentConfig(
                response_mime_type="application/json"
            )
            
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config
        )
        return response.text
    except Exception as e:
        print(f"Warning: Gemini API call failed: {e}. Falling back to deterministic mode.", file=sys.stderr)
        return None

def extract_json_block(text: str) -> Optional[Any]:
    """
    Extracts and parses JSON from response text, supporting markdown blocks and partial wraps.
    """
    if not text:
        return None
        
    text_stripped = text.strip()
    
    # Direct attempt
    try:
        return json.loads(text_stripped)
    except json.JSONDecodeError:
        pass
        
    # Markdown block attempt ```json ... ```
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass
            
    # Generic block attempt ``` ... ```
    match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass
            
    # Regex search for anything starting with [ and ending with ] or starting with { and ending with }
    match = re.search(r"(\[.*\]|\{.*\})", text_stripped, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass
            
    return None
