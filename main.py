import os
from google import genai
from dotenv import load_dotenv

def run_basic_interaction_test():
    # Load API keys from a local .env file if available
    load_dotenv()
    
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Warning: GEMINI_API_KEY environment variable is not set.")
        print("Please export GEMINI_API_KEY or configure a .env file.")
    
    print("Initializing Google GenAI client...")
    client = genai.Client()
    
    test_input = "Run 'uname -a && python3 --version' to output remote OS and Python environment details."
    print("Creating interaction with 'antigravity-preview-05-2026' on 'remote' environment...")
    
    # Setting environment='remote' provisions a fresh isolated remote sandbox
    interaction = client.interactions.create(
        agent="antigravity-preview-05-2026",
        input=test_input,
        environment="remote",
    )
    
    print("\n--- Interaction Results ---")
    print(f"Interaction ID: {interaction.id}")
    print(f"Environment ID: {interaction.environment_id}")
    print("----------------------------\n")
    print("Agent Response Output:")
    print(interaction.output_text)

if __name__ == "__main__":
    run_basic_interaction_test()
