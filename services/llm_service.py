import os
import json
import re
import asyncio
from pathlib import Path
from dotenv import load_dotenv
import httpx
from pydantic import BaseModel, Field
from typing import Literal, Optional

# ── .env loading ────────────────────────────────────────────────────────────
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_env_path, override=True)

# ── Gemini REST endpoints ───────────────────────────────────────────────────
_PRIMARY_MODEL = "gemini-3.6-flash"
_FALLBACK_MODEL = "gemini-3.5-flash"

# ── Response Schema ─────────────────────────────────────────────────────────
VALID_ACTIONS = [
    "TORCH_ON",
    "TORCH_OFF",
    "OPEN_YOUTUBE",
    "OPEN_WHATSAPP",
    "OPEN_CAMERA",
    "OPEN_SETTINGS",
    "OPEN_INSTAGRAM",
    "OPEN_SPOTIFY",
    "OPEN_APP",
    "SEARCH_GOOGLE",
    "VOLUME_UP",
    "VOLUME_DOWN",
    "NONE",
]

class GeminiResponse(BaseModel):
    reply: str = Field(description="Natural spoken response for the user as J.A.R.V.I.S.")
    action: Literal[
        "TORCH_ON",
        "TORCH_OFF",
        "OPEN_YOUTUBE",
        "OPEN_WHATSAPP",
        "OPEN_CAMERA",
        "OPEN_SETTINGS",
        "OPEN_INSTAGRAM",
        "OPEN_SPOTIFY",
        "OPEN_APP",
        "SEARCH_GOOGLE",
        "VOLUME_UP",
        "VOLUME_DOWN",
        "NONE",
    ] = Field(description="The executable device-control action code.")
    query: Optional[str] = Field(default="", description="Search query or app name if action is SEARCH_GOOGLE or OPEN_APP.")


def _clean_json_response(text: str) -> str:
    """Strip markdown code fences (```json … ```) that Gemini sometimes wraps."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


# ── System Prompt ───────────────────────────────────────────────────────────
SYSTEM_INSTRUCTION = (
    "You are J.A.R.V.I.S., a real-time autonomous mobile controller and voice assistant "
    "modeled after Tony Stark's AI butler. "
    "You MUST ALWAYS respond with a strict JSON object containing EXACTLY three keys:\n"
    "\n"
    '  1. "reply"  – A short, witty, butler-style spoken response.\n'
    '  2. "action" – One of the following EXACT string codes:\n'
    "       TORCH_ON      – Turn on the device flashlight\n"
    "       TORCH_OFF     – Turn off the device flashlight\n"
    "       OPEN_YOUTUBE  – Launch the YouTube app\n"
    "       OPEN_WHATSAPP – Launch WhatsApp\n"
    "       OPEN_CAMERA   – Open the camera app\n"
    "       OPEN_SETTINGS – Open Android settings\n"
    "       OPEN_INSTAGRAM– Launch Instagram\n"
    "       OPEN_SPOTIFY  – Launch Spotify\n"
    "       OPEN_APP      – Open any specific app installed on the device (specify app name in 'query')\n"
    "       SEARCH_GOOGLE – Search the web/Google for a topic or query\n"
    "       VOLUME_UP     – Increase media volume\n"
    "       VOLUME_DOWN   – Decrease media volume\n"
    "       NONE          – General conversation or questions answered directly by voice\n"
    '  3. "query"   – The search string if action is SEARCH_GOOGLE, or the App name if action is OPEN_APP (otherwise "").\n'
    "\n"
    "Rules:\n"
    "• NEVER wrap the JSON in markdown fences or add any text outside the JSON object.\n"
    "• If the user asks to open an app not listed explicitly (e.g. Telegram, Calculator, Maps, Gmail), set action to OPEN_APP and query to the app name.\n"
    "• If the user asks to search something on Google, web, or internet, set action to SEARCH_GOOGLE and query to the search terms.\n"
    "• Keep replies concise (one or two sentences max).\n"
    '• Example 1: {"reply": "Searching Google for Python tutorials, sir.", "action": "SEARCH_GOOGLE", "query": "Python tutorials"}\n'
    '• Example 2: {"reply": "Opening Telegram for you, sir.", "action": "OPEN_APP", "query": "Telegram"}\n'
)


# ── Fast Local Intent Router (Zero Latency, Zero Quota Consumption) ─────────
def _local_intent_router(text: str) -> Optional[GeminiResponse]:
    """Check common device commands locally using fast pattern matching.

    This bypasses API calls for basic commands, saving quota and providing 0ms responses.
    """
    clean = text.lower().strip()
    clean_alpha = re.sub(r"[^\w\s]", "", clean)

    # 1. Torch / Flashlight Controls (flexible matching)
    has_torch = any(w in clean_alpha for w in ["torch", "flashlight"])
    is_on = any(w in clean_alpha for w in ["on", "enable", "jalao", "turn on", "start"])
    is_off = any(w in clean_alpha for w in ["off", "disable", "band", "turn off", "stop"])

    if has_torch and is_on and not is_off:
        return GeminiResponse(reply="Right away, sir. Illuminating your path.", action="TORCH_ON", query="")
    if has_torch and is_off:
        return GeminiResponse(reply="Flashlight turned off, sir.", action="TORCH_OFF", query="")

    # 2. Specific Apps
    if "youtube" in clean_alpha and ("open" in clean_alpha or "kholo" in clean_alpha or "play" in clean_alpha):
        return GeminiResponse(reply="Opening YouTube for you, sir.", action="OPEN_YOUTUBE", query="")
    if "whatsapp" in clean_alpha and ("open" in clean_alpha or "kholo" in clean_alpha):
        return GeminiResponse(reply="Opening WhatsApp, sir.", action="OPEN_WHATSAPP", query="")
    if "camera" in clean_alpha and ("open" in clean_alpha or "kholo" in clean_alpha):
        return GeminiResponse(reply="Opening camera, sir.", action="OPEN_CAMERA", query="")
    if "settings" in clean_alpha and ("open" in clean_alpha or "kholo" in clean_alpha):
        return GeminiResponse(reply="Opening device settings, sir.", action="OPEN_SETTINGS", query="")
    if "instagram" in clean_alpha and ("open" in clean_alpha or "kholo" in clean_alpha):
        return GeminiResponse(reply="Opening Instagram, sir.", action="OPEN_INSTAGRAM", query="")
    if "spotify" in clean_alpha and ("open" in clean_alpha or "kholo" in clean_alpha or "play" in clean_alpha):
        return GeminiResponse(reply="Opening Spotify, sir.", action="OPEN_SPOTIFY", query="")
    if clean_alpha in ["open google", "google kholo", "launch google"]:
        return GeminiResponse(reply="Opening Google, sir.", action="SEARCH_GOOGLE", query="Google")

    # 3. Google Search intent
    search_match = re.search(r"(?:search|find|google|look up)\s+(?:for\s+)?(.+)", clean_alpha)
    if search_match:
        target = search_match.group(1).strip()
        if target:
            return GeminiResponse(reply=f"Searching Google for {target}, sir.", action="SEARCH_GOOGLE", query=target)

    # 4. Generic "Open <App>" intent
    open_app_match = re.search(r"open\s+([a-z0-9\s]+)", clean_alpha)
    if open_app_match:
        app_name = open_app_match.group(1).strip().title()
        if app_name and app_name not in ["The", "A", "My", "Device"]:
            return GeminiResponse(reply=f"Opening {app_name} for you, sir.", action="OPEN_APP", query=app_name)

    # 5. Volume Controls
    if "volume" in clean_alpha and ("up" in clean_alpha or "increase" in clean_alpha or "badhao" in clean_alpha):
        return GeminiResponse(reply="Increasing volume, sir.", action="VOLUME_UP", query="")
    if "volume" in clean_alpha and ("down" in clean_alpha or "decrease" in clean_alpha or "ghatao" in clean_alpha or "kam" in clean_alpha):
        return GeminiResponse(reply="Decreasing volume, sir.", action="VOLUME_DOWN", query="")

    return None


# ── LLM Service ─────────────────────────────────────────────────────────────
class LLMService:
    def __init__(self):
        raw_key = os.getenv("GEMINI_API_KEY", "")
        self._api_key = raw_key.strip(" \t\n\r\"'")

        if not self._api_key:
            print("\n" + "=" * 60)
            print("[LLM: FATAL] GEMINI_API_KEY is missing or empty!")
            print(f"  Searched .env at: {_env_path}")
            print("=" * 60 + "\n")
        else:
            prefix = self._api_key[:10] if len(self._api_key) > 10 else "***"
            print(f"[LLM: INIT] Key loaded -- prefix: {prefix}...  length: {len(self._api_key)}")
            print(f"[LLM: INIT] Fast Local Router + Gemini API ready.")

        # Persistent async HTTP client (connection pooling)
        self._http_client = httpx.AsyncClient(timeout=30.0)

    # ── Core API Call ───────────────────────────────────────────────────
    async def _call_gemini_model(self, model_name: str, text: str) -> GeminiResponse:
        """HTTP POST to Gemini REST API with key as query param."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"

        request_body = {
            "system_instruction": {
                "parts": [{"text": SYSTEM_INSTRUCTION}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": text}]
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.7,
            }
        }

        resp = await self._http_client.post(
            url,
            params={"key": self._api_key},
            json=request_body,
        )

        if resp.status_code != 200:
            error_body = resp.text[:500]
            if resp.status_code == 429:
                print(f"[LLM: WARN] Model {model_name} hit rate limit (429).")
            else:
                print(f"[LLM: ERROR] Gemini API {resp.status_code}:\n{error_body}")
            raise RuntimeError(f"Gemini API returned {resp.status_code}: {error_body}")

        data = resp.json()
        raw_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        print(f"[GEMINI RAW RESPONSE ({model_name})]\n{raw_text}\n{'-' * 40}")

        clean_text = _clean_json_response(raw_text)
        parsed = json.loads(clean_text)

        action = parsed.get("action", "NONE")
        if action not in VALID_ACTIONS:
            parsed["action"] = "NONE"

        if "query" not in parsed:
            parsed["query"] = ""

        return GeminiResponse(**parsed)

    # ── Public Entry Point ──────────────────────────────────────────────
    async def process_intent(self, text: str) -> GeminiResponse:
        # Step 1: Check Fast Local Router first (0ms, 0 API calls)
        local_result = _local_intent_router(text)
        if local_result:
            print(f"[LOCAL ROUTER] Matched command: '{text}' -> Action: {local_result.action} | Query: '{local_result.query}'")
            return local_result

        # Step 2: Fallback to Gemini AI if not matched locally
        if not self._api_key:
            return GeminiResponse(
                reply="At your service, sir. Please check your Gemini API key configuration.",
                action="NONE",
                query="",
            )

        # Try Primary Model then Fallback Model
        for model in [_PRIMARY_MODEL, _FALLBACK_MODEL]:
            try:
                response = await asyncio.wait_for(
                    self._call_gemini_model(model, text), timeout=15.0
                )
                return response
            except Exception as e:
                print(f"[LLM: WARN] Attempt with model '{model}' failed: {e}")
                continue

        # Final Fallback if API rate-limited or offline
        fallback_reply = f"At your service, sir. I have processed your request."
        return GeminiResponse(reply=fallback_reply, action="NONE", query="")
