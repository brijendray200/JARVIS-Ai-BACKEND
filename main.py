import base64
import json
import traceback
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocketState
import uvicorn

from services.stt_service import STTService
from services.llm_service import LLMService
from services.tts_service import TTSService
from config import settings

# Initialize services
stt_service = STTService()
llm_service = LLMService()

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Warming up J.A.R.V.I.S. models...")
    stt_service.initialize()
    print("Models warmed up.")
    yield
    print("Shutting down J.A.R.V.I.S. backend.")

app = FastAPI(title="JARVIS Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Safe WebSocket Send ─────────────────────────────────────────────────────
async def _safe_send_json(
    websocket: WebSocket,
    payload: dict,
    send_lock: asyncio.Lock,
) -> bool:
    """Send JSON only if the socket is still alive. Returns True on success."""
    try:
        if websocket.client_state != WebSocketState.CONNECTED:
            print("[WS: SKIP] Client already disconnected – dropping payload.")
            return False

        async with send_lock:
            await websocket.send_json(payload)
        return True

    except (WebSocketDisconnect, RuntimeError) as e:
        # RuntimeError: "Cannot call 'send' once a close message has been sent."
        print(f"[WS: SKIP] Send suppressed (client gone): {e}")
        return False
    except Exception as e:
        print(f"[WS: ERROR] Unexpected send failure: {e}")
        return False


# ── Pipeline ─────────────────────────────────────────────────────────────────
async def process_and_respond(
    message: dict,
    websocket: WebSocket,
    send_lock: asyncio.Lock,
):
    transcribed_text = ""

    try:
        audio_bytes = None

        # Defensive parsing
        if "bytes" in message:
            audio_bytes = message["bytes"]
        elif "text" in message:
            raw_text = message["text"].strip()

            # Check if it's JSON
            audio_b64 = ""
            try:
                data = json.loads(raw_text)
                if "audio" in data:
                    audio_b64 = data["audio"]
                elif "text" in data:
                    transcribed_text = data["text"]
                else:
                    audio_b64 = ""
            except json.JSONDecodeError:
                # Not JSON, treat as raw string (potentially base64)
                audio_b64 = raw_text

            if not transcribed_text and audio_b64:
                # Strip data URL prefix if present
                if "base64," in audio_b64:
                    audio_b64 = audio_b64.split("base64,")[1]

                audio_b64 = audio_b64.strip()
                try:
                    audio_bytes = base64.b64decode(audio_b64)
                except Exception as e:
                    print(f"[WS: ERROR] Base64 decoding failed: {e}")

        if audio_bytes:
            print(f"[WS: INGESTION] Decoded {len(audio_bytes)} raw audio bytes")
            transcribed_text = await stt_service.transcribe(audio_bytes)

        # ── Early bail-out if client vanished during STT ────────────────
        if websocket.client_state != WebSocketState.CONNECTED:
            print("[PIPELINE] Client disconnected during STT – aborting pipeline.")
            return

        # Handle Empty Audio / Noise
        normalized_text = transcribed_text.lower().strip()
        if not normalized_text:
            print("[PIPELINE] Empty or silent audio transcript – dropping payload.")
            return

        if normalized_text in ["hello", "hi jarvis", "jarvis", "hi", "hey jarvis"]:
            print("[GREETING] Wake word / greeting detected.")
            reply_text = "Yes sir, I am listening. How can I assist you?"
            action_payload = "NONE"
            query_payload = ""
        else:
            # LLM Processing (Local Router first, then Gemini AI)
            gemini_response = await llm_service.process_intent(transcribed_text)
            reply_text = gemini_response.reply
            action_payload = gemini_response.action
            query_payload = gemini_response.query or ""
            print(f"[GEMINI] Action: {action_payload} | Query: {query_payload} | Reply: {reply_text}")

        # ── Early bail-out if client vanished during LLM ────────────────
        if websocket.client_state != WebSocketState.CONNECTED:
            print("[PIPELINE] Client disconnected during LLM – skipping TTS & send.")
            return

        # TTS Synthesis
        audio_base64 = await TTSService.generate_audio_base64(reply_text)

        # WS Send Phase
        response_payload = {
            "transcription": transcribed_text,
            "reply": reply_text,
            "action": action_payload,
            "query": query_payload if 'query_payload' in locals() else "",
            "audio": audio_base64,
        }

        sent = await _safe_send_json(websocket, response_payload, send_lock)
        if sent:
            print("[WS: SENT] Payload delivered successfully.")
            print("-" * 50)

    except asyncio.CancelledError:
        print("[PIPELINE] Task cancelled (client disconnected).")
        return

    except Exception as inner_e:
        print("[PIPELINE CRASH] Unhandled exception occurred:")
        traceback.print_exc()

        error_payload = {
            "error": str(inner_e),
            "reply": "An error occurred, sir.",
            "transcription": transcribed_text,
            "action": "NONE",
            "query": "",
            "audio": "",
        }
        await _safe_send_json(websocket, error_payload, send_lock)


# ── WebSocket Endpoint ───────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    client_info = websocket.client
    print(f"[WS: CONNECTED] Client connected from {client_info}")

    send_lock = asyncio.Lock()
    pending_tasks: set[asyncio.Task] = set()

    try:
        while True:
            # Wait for messages from the client
            message = await websocket.receive()

            # Lightweight text ping support – responds immediately
            if "text" in message and message["text"].strip().lower() == "ping":
                await _safe_send_json(websocket, {"pong": True}, send_lock)
                continue

            # Process heavy pipeline asynchronously so we don't block ping-pongs
            task = asyncio.create_task(
                process_and_respond(message, websocket, send_lock)
            )
            pending_tasks.add(task)
            task.add_done_callback(pending_tasks.discard)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WS: ERROR] Connection error: {e}")
    finally:
        # Cancel any in-flight pipeline tasks so they don't try to send on a dead socket
        for task in pending_tasks:
            task.cancel()
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)
            print(f"[WS: CLEANUP] Cancelled {len(pending_tasks)} in-flight task(s).")

        print(f"[WS: DISCONNECTED] Client disconnected")
        try:
            await websocket.close()
        except Exception:
            pass  # Already closed – suppress


if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=True)
