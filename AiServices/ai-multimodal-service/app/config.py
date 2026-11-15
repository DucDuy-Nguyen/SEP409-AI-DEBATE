from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ADPP AI Multimodal Service (DeepFace + Whisper)"
    detector_backend: str = "yunet"
    fallback_detector_backend: str = "opencv"
    whisper_model_size: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    prewarm_models: bool = True
    evaluator_service_url: str = (
        "https://adpp-ai-evaluator.greenstone-4d67d46a.indonesiacentral.azurecontainerapps.io"
    )
    system_service_url: str = "http://localhost:5001"

    # Deepgram Realtime STT (Preset chuan Deepgram Web: WebM/Opus, Raw Voice, 300ms, Smart Format OFF, Nova-2, vi)
    deepgram_api_key: str = ""
    deepgram_default_model: str = "nova-2"
    deepgram_default_language: str = "vi"
    deepgram_default_endpointing_ms: int = 300
    deepgram_default_smart_format: bool = False
    deepgram_default_punctuate: bool = True
    deepgram_default_encoding: str = "webm"
    deepgram_default_sample_rate: int = 16000
    deepgram_utterance_end_ms: int = 1000
    deepgram_keepalive_interval_s: float = 8.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
