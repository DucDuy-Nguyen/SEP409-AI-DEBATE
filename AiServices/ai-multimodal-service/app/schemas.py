"""
Pydantic schemas cho AI Multimodal Service (DeepFace Facial Emotion + Faster-Whisper Voice Analysis).
"""
from typing import Optional
from pydantic import BaseModel, Field


class FaceRegion(BaseModel):
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0


class FrameAnalysisRequest(BaseModel):
    image_base64: str = Field(..., description="Anh frame tu webcam dang base64 (co hoac khong co data:image/... prefix)")
    timestamp: Optional[float] = Field(default=None, description="Thoi diem frame (giay tu luc bat dau luot noi)")
    detector_backend: Optional[str] = Field(default=None, description="Backend nhan dien khuon mat (mac dinh: yunet)")


class FrameAnalysisResult(BaseModel):
    face_detected: bool = Field(..., description="Co phat hien khuon mat hop le cua nguoi tranh bien khong")
    dominant_emotion: str = Field(default="neutral", description="Cam xuc chiem uu the")
    dominant_score: float = Field(default=0.0, description="Diem phan tram cua cam xuc chiem uu the (0-100)")
    emotion_scores: dict[str, float] = Field(
        default_factory=lambda: {
            "neutral": 0.0,
            "happy": 0.0,
            "surprise": 0.0,
            "sad": 0.0,
            "angry": 0.0,
            "fear": 0.0,
            "disgust": 0.0,
        }
    )
    face_confidence: float = Field(default=0.0, description="Do tin cay khuon mat tu detector (0-1)")
    region: Optional[FaceRegion] = Field(default=None, description="Toa do bounding box khuon mat")
    composure_instant: float = Field(default=0.0, description="Chi so diem tinh tuc thoi (neutral + happy %)")
    timestamp: Optional[float] = None


class EmotionSample(BaseModel):
    time: float = Field(default=0.0, description="Thoi diem mau cam xuc (giay)")
    dominant: str = Field(..., description="Cam xuc chu dao tai thoi diem do")
    scores: dict[str, float] = Field(default_factory=dict)
    face_detected: bool = Field(default=True)


class VoiceMetrics(BaseModel):
    transcript_text: str = Field(default="", description="Van ban nhan dien tu giong noi (Faster-Whisper)")
    duration_seconds: float = Field(default=0.0, ge=0.0)
    word_count: int = Field(default=0, ge=0)
    wpm: float = Field(default=0.0, ge=0.0, description="Toc do noi (tu / phut)")
    pace_evaluation: str = Field(default="Không có giọng nói")
    pace_score: float = Field(default=50.0, ge=0.0, le=100.0)
    filler_count: int = Field(default=0, ge=0, description="So lan lap tu dem ngap ngung (ờ, ừm, kiểu, à, ừ...)")
    filler_words_found: dict[str, int] = Field(default_factory=dict, description="Chi tiet so lan xuat hien tung tu dem")
    fluency_score: float = Field(default=100.0, ge=0.0, le=100.0)


class FacialMetrics(BaseModel):
    total_frames_analyzed: int = Field(default=0, ge=0)
    face_detected_frames: int = Field(default=0, ge=0)
    eye_contact_rate: float = Field(default=0.0, ge=0.0, le=100.0, description="Ti le % khung hinh giu eye contact voi camera")
    dominant_emotion: str = Field(default="neutral")
    composure_score: float = Field(
        default=0.0, ge=0.0, le=100.0, description="Chi so diem tinh (ti le Neutral + Happy %)"
    )
    emotion_counts: dict[str, int] = Field(default_factory=dict)
    emotion_pct: dict[str, float] = Field(default_factory=dict, description="Phan bo % 7 cam xuc khuon mat")


class DeliveryAnalyticsPayload(BaseModel):
    """
    Goi du lieu phong thai chuan hoa de gui sang SystemService (.NET) va ai-evaluator-service.
    """
    dominant_emotion: str = "neutral"
    eye_contact_rate: float = 0.0
    composure_score: float = 0.0
    confidence_score: float = 0.0
    wpm: float = 0.0
    pace_evaluation: str = ""
    pace_score: float = 0.0
    filler_count: int = 0
    fluency_score: float = 0.0
    overall_demeanor_score: float = 0.0
    emotion_breakdown: dict[str, float] = Field(default_factory=dict)


class MultimodalTurnRequest(BaseModel):
    """
    Input phan tich 1 luot tranh bien da phuong thuc (Vision + Voice).
    Ho tro truyen:
    - audio_base64: file ghi am (.wav / .webm / .ogg / .mp3) ma hoa base64
    - frames_base64: danh sach cac key-frame chup trong luot noi (DeepFace se phan tich tung frame)
    - emotion_timeline: danh sach cac ket qua cam xuc da phan tich san tu /analyze-frame trong luc noi
    - duration_seconds: thoi luong luot noi (giay)
    - transcript_override: tuy chon van ban neu nguoi dung da nhap hoac chinh sua
    - include_report_chart: co tao bieu do bao cao PNG (base64) nhu debate_session_analyzer.py khong
    """
    audio_base64: Optional[str] = Field(default=None, description="File audio ghi am luot noi dang base64")
    frames_base64: list[str] = Field(default_factory=list, description="Danh sach anh key-frame base64 de chay DeepFace")
    emotion_timeline: list[EmotionSample] = Field(
        default_factory=list, description="Timeline cam xuc da thu thap tu /analyze-frame"
    )
    total_frames_captured: Optional[int] = Field(default=None, ge=0)
    duration_seconds: float = Field(default=0.0, ge=0.0, description="Thoi luong luot tranh bien (giay)")
    transcript_override: Optional[str] = Field(default=None, description="Van ban lap luan (neu truyen san hoac fallback)")
    include_report_chart: bool = Field(default=True, description="Xuat bieu do PNG bao cao truc quan dang base64")


class MultimodalTurnResult(BaseModel):
    overall_demeanor_score: float = Field(
        ..., ge=0.0, le=100.0, description="Diem phong thai tong the = 0.4*Composure + 0.3*Pace + 0.3*Fluency"
    )
    voice: VoiceMetrics
    facial: FacialMetrics
    delivery_analytics: DeliveryAnalyticsPayload
    report_chart_base64: Optional[str] = Field(
        default=None, description="Anh bieu do bao cao PNG (data:image/png;base64,...)"
    )


class IntegratedDebateEvaluationRequest(BaseModel):
    """
    Input tich hop: Phan tich Multimodal (DeepFace + Whisper) + Cham diem lap luan (AI Evaluator).
    """
    motion: str = Field(..., description="Chu de tranh bien")
    side: str = Field(default="pro", description="pro hoac con")
    stage: str = Field(default="rebuttal", description="opening, rebuttal, hoac closing")
    opponent_argument_text: Optional[str] = Field(default=None)
    turn_data: MultimodalTurnRequest
    existing_multimodal_result: Optional[MultimodalTurnResult] = Field(
        default=None,
        description="Neu da phan tich xong o buoc /analyze-turn thi truyen nguyen ket qua sang de giu nguyen 100% cac chi so phong thai",
    )


class IntegratedDebateEvaluationResult(BaseModel):
    multimodal: MultimodalTurnResult
    argument_text_used: str
    content_evaluation: Optional[dict] = Field(
        default=None, description="Ket qua cham diem noi dung lap luan tu ai-evaluator-service"
    )
    evaluation_error: Optional[str] = None

