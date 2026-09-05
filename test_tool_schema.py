import asyncio
import json
from pydantic import BaseModel, Field
from typing import Optional, List
from google import genai
from google.genai import types
from services.search_service import SearchService
import os

os.environ["GEMINI_API_KEY"] = "DUMMY_FOR_TESTING" # Assuming .env has it or I don't actually call the api, just checking if schema parses

class ActionItem(BaseModel):
    type: str

class BrainResponse(BaseModel):
    speech_text: str = Field(description="Natural spoken response for the user as J.A.R.V.I.S.")
    action: Optional[List[ActionItem]] = Field(None)

def search_web(query: str) -> str:
    """Searches the web for information using DuckDuckGo."""
    return "Dummy search results"

try:
    client = genai.Client()
    config = types.GenerateContentConfig(
        tools=[search_web],
        response_mime_type="application/json",
        response_schema=BrainResponse,
    )
    print("Schema parsing OK.")
except Exception as e:
    print(f"Error: {e}")
