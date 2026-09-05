import edge_tts
import base64
from config import settings

class TTSService:
    @staticmethod
    async def generate_audio_base64(text: str) -> str:
        """
        Generates TTS audio using edge-tts and returns it as a Base64-encoded MP3 string.
        """
        if not text:
            print("[TTS: SYNTHESIS] Generated 0 MP3 bytes")
            return ""
            
        # Fallback voice specified by user, overrides config if needed
        voice = "en-US-ChristopherNeural"
        
        try:
            communicate = edge_tts.Communicate(text, voice)
            audio_data = bytearray()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_data.extend(chunk["data"])
            
            if not audio_data:
                print("[TTS: SYNTHESIS] Generated 0 MP3 bytes")
                return ""
                
            print(f"[TTS: SYNTHESIS] Generated {len(audio_data)} MP3 bytes")
            base64_audio = base64.b64encode(audio_data).decode('utf-8')
            return base64_audio
        except Exception as e:
            print(f"[TTS: ERROR] Network/Edge-TTS failed: {e}")
            return ""
