from dotenv import load_dotenv, find_dotenv
import os
import ee
from agents import Agent, RunConfig, AsyncOpenAI, OpenAIChatCompletionsModel

# Load environment variables
load_dotenv(find_dotenv())

def initialize_earth_engine():
    """Initialize Earth Engine"""
    try:
        ee.Initialize(project='ee-ewe111vijay')
        print("Earth Engine initialized successfully")
    except Exception as e:
        print(f"Error initializing Earth Engine: {e}")

def setup_gemini():
    """Setup Gemini model configuration"""
    provider = AsyncOpenAI(
        api_key=os.getenv("GEMINI_API_KEY"),
        base_url="https://generativelanguage.googleapis.com/v1beta"
    )

    model = OpenAIChatCompletionsModel(
        model="gemini-1.5-flash",
        openai_client=provider
    )

    return RunConfig(
        model=model,
        model_provider=provider,
        tracing_disabled=True
    )