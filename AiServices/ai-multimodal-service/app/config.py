from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ADPP AI Multimodal Service (DeepFace + Whisper)"
    detector_backend: str = "yunet"
    fallback_detector_backend: str = "opencv"
    # Nguong diem YuNet cua DeepFace (mac dinh thu vien 0.9). DeepFace them vien 50% roi thu anh ve 640px truoc khi
    # detect, mat webcam nho lai va diem tut xuong ~0.76-0.87 -> bi loai het. analyze_single_frame van loc them conf >= 0.45.
    yunet_score_threshold: float = 0.6
    whisper_model_size: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    # 1 = greedy. Do tren CPU (small, int8): 72.5 s am thanh 45.7 s voi beam 5 -> 29.9 s voi beam 1, transcript giong het.
    whisper_beam_size: int = 1
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

    # Azure AI Speech TTS (AI doi thu doc to, POST /multimodal/tts). Free F0: 0.5M ky tu neural / thang.
    # Region phai nam trong vung subscription cho phep (Azure for Students: japaneast / japanwest / centralindia).
    azure_speech_key: str = ""
    azure_speech_region: str = ""
    azure_tts_voice: str = "vi-VN-NamMinhNeural"
    # Danh sach giong duoc phep chon (endpoint khong phai proxy tu do toi key Speech)
    # Mac dinh: 6 giong tieng Viet goc co tren japaneast (2026-11-20), xem azure_tts.VOICE_CATALOG
    azure_tts_voices: str = (
        "vi-VN-NamMinhNeural,vi-VN-HoaiMyNeural,vi-VN-Grant:MAI-Voice-2.1-Flash,vi-VN-Harper:MAI-Voice-2.1-Flash,"
        "vi-VN-Grant:MAI-Voice-2.1,vi-VN-Harper:MAI-Voice-2.1"
    )
    azure_tts_rate: str = "+5%"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
