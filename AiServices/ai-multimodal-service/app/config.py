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
    evaluator_service_url: str = "http://localhost:8000"
    remote_evaluator_service_url: str = (
        "https://adpp-ai-evaluator.greenstone-4d67d46a.indonesiacentral.azurecontainerapps.io"
    )
    system_service_url: str = "http://localhost:5001"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
