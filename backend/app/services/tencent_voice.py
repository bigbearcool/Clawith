"""Tencent Cloud Voice Service (ASR + TTS)."""

import base64
import hashlib
import hmac
import time
import uuid
from datetime import datetime
from loguru import logger
import httpx
import json

from app.constants.voice import DEFAULT_VOICE_ID, get_voice_info


class TencentVoiceService:
    """Tencent Cloud Voice Service for ASR and TTS."""

    def __init__(self, secret_id: str, secret_key: str):
        self.secret_id = secret_id
        self.secret_key = secret_key
        self.asr_host = "asr.tencentcloudapi.com"
        self.tts_host = "tts.tencentcloudapi.com"

    def _sign(self, payload: str, host: str, action: str, version: str, service: str) -> dict:
        """Generate Tencent Cloud API signature.

        Args:
            payload: Request body (JSON string)
            host: API host
            action: API action name
            version: API version
            service: Service name (asr, tts)

        Returns:
            Headers dict with signature
        """
        timestamp = int(time.time())
        date = datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")

        http_request_method = "POST"
        canonical_uri = "/"
        canonical_querystring = ""
        ct = "application/json; charset=utf-8"
        canonical_headers = f"content-type:{ct}\nhost:{host}\n"
        signed_headers = "content-type;host"
        hashed_request_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        canonical_request = (
            f"{http_request_method}\n"
            f"{canonical_uri}\n"
            f"{canonical_querystring}\n"
            f"{canonical_headers}\n"
            f"{signed_headers}\n"
            f"{hashed_request_payload}"
        )

        algorithm = "TC3-HMAC-SHA256"
        credential_scope = f"{date}/{service}/tc3_request"
        hashed_canonical_request = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
        string_to_sign = f"{algorithm}\n{timestamp}\n{credential_scope}\n{hashed_canonical_request}"

        secret_date = hmac.new(f"TC3{self.secret_key}".encode("utf-8"), date.encode("utf-8"), hashlib.sha256).digest()
        secret_service = hmac.new(secret_date, service.encode("utf-8"), hashlib.sha256).digest()
        secret_signing = hmac.new(secret_service, "tc3_request".encode("utf-8"), hashlib.sha256).digest()
        signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

        authorization = (
            f"{algorithm} "
            f"Credential={self.secret_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, "
            f"Signature={signature}"
        )

        headers = {
            "Authorization": authorization,
            "Content-Type": ct,
            "Host": host,
            "X-TC-Action": action,
            "X-TC-Version": version,
            "X-TC-Timestamp": str(timestamp),
        }

        return headers

    async def asr_one_sentence(self, audio_bytes: bytes, format: str = "opus", sample_rate: int = 16000) -> str:
        """Speech-to-Text using Tencent Cloud ASR.

        Args:
            audio_bytes: Audio binary data
            format: Audio format (opus, mp3, wav)
            sample_rate: Sample rate (8000, 16000)

        Returns:
            Transcribed text
        """
        # Encode audio to base64
        audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")

        # Request payload
        payload_dict = {
            "EngSerViceType": "16k",  # 16k model
            "SourceType": 1,  # URL or base64
            "VoiceFormat": format,
            "Data": audio_base64,
            "DataLen": len(audio_bytes),
        }
        payload = json.dumps(payload_dict)

        # Sign request
        headers = self._sign(payload, self.asr_host, "SentenceRecognition", "2019-06-14", "asr")

        # Send request
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(f"https://{self.asr_host}", headers=headers, content=payload)
                response.raise_for_status()
                result = response.json()

                # Parse result
                if result.get("Response", {}).get("Error"):
                    error = result["Response"]["Error"]
                    logger.error(f"[Tencent ASR] Error: {error}")
                    raise RuntimeError(f"ASR failed: {error.get('Message')}")

                # Extract text
                text = result.get("Response", {}).get("Result", "")
                logger.info(f"[Tencent ASR] Success: {text[:50]}...")
                return text

            except Exception as e:
                logger.error(f"[Tencent ASR] Request failed: {e}")
                raise

    async def tts_synthesis(
        self,
        text: str,
        voice_type: str = DEFAULT_VOICE_ID,
        speed: float = 0.0,
        volume: float = 0.0,
        sample_rate: int = 16000,
        codec: str = "mp3",
    ) -> bytes:
        """Text-to-Speech using Tencent Cloud TTS.

        Args:
            text: Text to synthesize
            voice_type: Voice ID (e.g., "101001")
            speed: Speed (-2 to 6, 0 = normal)
            volume: Volume (-10 to 10, 0 = normal)
            sample_rate: Sample rate (8000, 16000, 24000)
            codec: Audio format (mp3, wav, pcm)

        Returns:
            Audio binary data
        """
        # Request payload
        payload_dict = {
            "Text": text,
            "SessionId": str(uuid.uuid4()),
            "VoiceType": int(voice_type),
            "Speed": speed,
            "Volume": volume,
            "SampleRate": sample_rate,
            "Codec": codec,
        }
        payload = json.dumps(payload_dict)

        # Sign request
        headers = self._sign(payload, self.tts_host, "TextToVoice", "2019-08-23", "tts")

        # Send request
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(f"https://{self.tts_host}", headers=headers, content=payload)
                response.raise_for_status()
                result = response.json()

                # Parse result
                if result.get("Response", {}).get("Error"):
                    error = result["Response"]["Error"]
                    logger.error(f"[Tencent TTS] Error: {error}")
                    raise RuntimeError(f"TTS failed: {error.get('Message')}")

                # Decode audio
                audio_base64 = result.get("Response", {}).get("Audio", "")
                audio_bytes = base64.b64decode(audio_base64)

                logger.info(
                    f"[Tencent TTS] Success: voice={voice_type}, text_len={len(text)}, audio_size={len(audio_bytes)}"
                )
                return audio_bytes

            except Exception as e:
                logger.error(f"[Tencent TTS] Request failed: {e}")
                raise
