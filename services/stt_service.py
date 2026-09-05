import io
import asyncio
import subprocess
import numpy as np
from faster_whisper import WhisperModel
from config import settings

KNOWN_HALLUCINATIONS = [
    "i'm dead",
    "im dead",
    "dead",
    "subtitles by",
    "subtitled by",
    "thank you for watching",
    "thanks for watching",
    "amara.org",
    "bye",
    "bye bye",
    "subscribe",
    "like and subscribe",
]

class STTService:
    _instance = None
    _model = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(STTService, cls).__new__(cls)
        return cls._instance

    def initialize(self):
        if self._model is None:
            print(f"Initializing WhisperModel with size '{settings.WHISPER_MODEL_SIZE}'")
            try:
                self._model = WhisperModel(settings.WHISPER_MODEL_SIZE, device="auto", compute_type="int8")
                print("WhisperModel initialized successfully.")
            except Exception as e:
                print(f"STT Initialization Error: {e}")

    async def transcribe(self, audio_bytes: bytes) -> str:
        if not audio_bytes:
            print('[STT: TRANSCRIPTION] Result: ""')
            return ""
            
        if self._model is None:
            self.initialize()
            if self._model is None:
                print('[STT: TRANSCRIPTION] Result: ""')
                return ""
            
        def _do_transcribe():
            try:
                # Use FFmpeg to decode the in-memory stream to 16kHz mono PCM float32
                process = subprocess.run(
                    [
                        "ffmpeg",
                        "-i", "pipe:0",
                        "-f", "s16le",
                        "-ac", "1",
                        "-ar", "16000",
                        "pipe:1"
                    ],
                    input=audio_bytes,
                    capture_output=True,
                    check=True
                )
                
                audio_np = np.frombuffer(process.stdout, dtype=np.int16).astype(np.float32) / 32768.0

                if len(audio_np) == 0:
                    return ""

                # Check Root Mean Square (RMS) volume level to filter out silence/static noise
                rms = float(np.sqrt(np.mean(audio_np**2)))
                if rms < 0.008:
                    print(f"[STT: SILENCE] Low audio level (RMS: {rms:.5f}) – skipping Whisper.")
                    return ""
                
                # faster_whisper transcription with anti-hallucination settings
                segments, info = self._model.transcribe(
                    audio_np,
                    beam_size=5,
                    language="en",
                    no_speech_threshold=0.6,
                    condition_on_previous_text=False,
                )
                text = " ".join([segment.text for segment in segments]).strip()
                
                # Filter out known Whisper hallucination strings
                text_clean = text.lower().strip(" .!?,")
                for hall in KNOWN_HALLUCINATIONS:
                    if hall in text_clean:
                        print(f"[STT: FILTERED] Hallucination detected ('{text}') – clearing.")
                        return ""

                return text
            except FileNotFoundError:
                print("STT Error: FFmpeg not found in PATH.")
                return ""
            except subprocess.CalledProcessError as e:
                err_msg = e.stderr.decode(errors="ignore") if e.stderr else "Unknown FFmpeg error"
                print(f"STT Error (FFmpeg decoding failed): {err_msg}")
                return ""
            except Exception as e:
                print(f"STT Error (Unexpected): {e}")
                return ""
            
        # Run in executor to prevent blocking the event loop
        try:
            loop = asyncio.get_running_loop()
            transcribed_text = await loop.run_in_executor(None, _do_transcribe)
            print(f'[STT: TRANSCRIPTION] Result: "{transcribed_text}"')
            return transcribed_text
        except Exception as e:
            print(f"STT Execution Error: {e}")
            return ""
