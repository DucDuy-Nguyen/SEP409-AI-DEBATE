"""
Core service phan tich da phuong thuc (Vision + Voice) tich hop tu D:\\Emotion-Test\\deepface:
- DeepFace + YuNet: nhan dien khuon mat & 7 trang thai cam xuc realtime
- Faster-Whisper: nhan dien giong noi tieng Viet (STT), tinh WPM, Pace Score, bat tu dem (Filler Words)
- Matplotlib (Agg): xuat bieu do bao cao truc quan (Pie chart cam xuc + Summary card)
"""
import base64
import io
import logging
import os
import re
import sys
import tempfile
import threading
import time
from typing import Optional

import cv2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Dam bao D:\Emotion-Test\deepface duoc uu tien import neu co tren may
_LOCAL_DEEPFACE_REPO = r"D:\Emotion-Test\deepface"
if os.path.isdir(_LOCAL_DEEPFACE_REPO) and _LOCAL_DEEPFACE_REPO not in sys.path:
    sys.path.insert(0, _LOCAL_DEEPFACE_REPO)

from deepface import DeepFace

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None  # type: ignore

from app.config import get_settings
from app.schemas import (
    DeliveryAnalyticsPayload,
    EmotionSample,
    FaceRegion,
    FacialMetrics,
    FrameAnalysisResult,
    MultimodalTurnRequest,
    MultimodalTurnResult,
    VoiceMetrics,
)

logger = logging.getLogger(__name__)

EMOTIONS = ["neutral", "happy", "surprise", "sad", "angry", "fear", "disgust"]
FILLER_WORDS = ["ờ", "ừm", "kiểu", "à", "ừ", "um", "uh"]

_model_lock = threading.Lock()
_whisper_model: Optional[object] = None
_deepface_ready: bool = False
_active_detector_backend: str = "yunet"


def get_model_status() -> dict:
    return {
        "deepface_ready": _deepface_ready,
        "detector_backend": _active_detector_backend,
        "whisper_ready": _whisper_model is not None,
        "deepface_source": getattr(DeepFace, "__file__", "unknown"),
    }


def ensure_models_loaded(load_whisper: bool = True) -> dict:
    global _whisper_model, _deepface_ready, _active_detector_backend
    settings = get_settings()

    with _model_lock:
        if not _deepface_ready:
            dummy_img = np.zeros((150, 150, 3), dtype=np.uint8)
            for backend in [settings.detector_backend, settings.fallback_detector_backend]:
                try:
                    DeepFace.analyze(
                        dummy_img,
                        actions=["emotion"],
                        detector_backend=backend,
                        enforce_detection=False,
                        silent=True,
                    )
                    _active_detector_backend = backend
                    _deepface_ready = True
                    logger.info("DeepFace emotion model pre-warmed with backend='%s'", backend)
                    break
                except Exception as exc:
                    logger.warning("DeepFace pre-warm warning with backend='%s': %s", backend, exc)

        if load_whisper and _whisper_model is None and WhisperModel is not None:
            try:
                _whisper_model = WhisperModel(
                    settings.whisper_model_size,
                    device=settings.whisper_device,
                    compute_type=settings.whisper_compute_type,
                )
                logger.info("Faster-Whisper ('%s') loaded successfully.", settings.whisper_model_size)
            except Exception as exc:
                logger.warning("Faster-Whisper load warning: %s", exc)

    return get_model_status()


def decode_base64_image(image_base64: str) -> np.ndarray:
    """Giai ma chuoi base64 (co hoac khong co prefix data:image/...) thanh BGR numpy array cho OpenCV."""
    raw_b64 = image_base64.strip()
    if "," in raw_b64 and raw_b64.startswith("data:"):
        raw_b64 = raw_b64.split(",", 1)[1]
    img_bytes = base64.b64decode(raw_b64)
    np_arr = np.frombuffer(img_bytes, dtype=np.uint8)
    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("Khong the giai ma anh tu chuoi base64")
    return frame


def analyze_single_frame(
    frame: np.ndarray,
    timestamp: Optional[float] = None,
    detector_backend: Optional[str] = None,
) -> FrameAnalysisResult:
    """
    Phan tich 1 frame hinh anh bang DeepFace (YuNet/OpenCV), loc khuon mat nguoi tranh bien chinh
    theo dung thuat toan trong debate_session_analyzer.py.
    """
    ensure_models_loaded(load_whisper=False)
    backend = detector_backend or _active_detector_backend
    frame_h, frame_w = frame.shape[:2]

    try:
        results = DeepFace.analyze(
            frame,
            actions=["emotion"],
            detector_backend=backend,
            enforce_detection=False,
            silent=True,
        )
    except Exception as exc:
        logger.debug("DeepFace analyze error on backend %s: %s", backend, exc)
        if backend != "opencv":
            try:
                results = DeepFace.analyze(
                    frame,
                    actions=["emotion"],
                    detector_backend="opencv",
                    enforce_detection=False,
                    silent=True,
                )
            except Exception:
                results = []
        else:
            results = []

    valid_faces = []
    if isinstance(results, dict):
        results = [results]

    if isinstance(results, list):
        for r in results:
            if not isinstance(r, dict):
                continue
            region = r.get("region", {}) or {}
            w = int(region.get("w", 0))
            h = int(region.get("h", 0))
            conf = float(r.get("face_confidence", 0.0) or 0.0)

            # Kiem tra khuon mat hop le (tranh khung mac dinh toan man hinh khi khong co mat)
            min_dim = min(40, int(min(frame_w, frame_h) * 0.12))
            is_full_frame_fallback = (w >= frame_w - 10 and h >= frame_h - 10)
            if w >= min_dim and h >= min_dim and not is_full_frame_fallback and conf >= 0.45:
                valid_faces.append(r)

    if not valid_faces:
        return FrameAnalysisResult(
            face_detected=False,
            dominant_emotion="neutral",
            dominant_score=0.0,
            face_confidence=0.0,
            region=None,
            composure_instant=0.0,
            timestamp=timestamp,
        )

    # Uu tien nguoi tranh bien chinh (khuon mat gan camera nhat / dien tich lon nhat)
    valid_faces.sort(
        key=lambda item: int(item.get("region", {}).get("w", 0)) * int(item.get("region", {}).get("h", 0)),
        reverse=True,
    )
    primary = valid_faces[0]
    reg = primary.get("region", {}) or {}
    raw_emotions = primary.get("emotion", {}) or {}
    emotion_scores = {k: round(float(raw_emotions.get(k, 0.0)), 2) for k in EMOTIONS}
    dominant = str(primary.get("dominant_emotion", "neutral")).lower()
    if dominant not in emotion_scores and emotion_scores:
        dominant = max(emotion_scores, key=emotion_scores.get)
    dom_score = emotion_scores.get(dominant, 0.0)
    composure_instant = round(
        min(100.0, emotion_scores.get("neutral", 0.0) + emotion_scores.get("happy", 0.0)), 1
    )

    return FrameAnalysisResult(
        face_detected=True,
        dominant_emotion=dominant,
        dominant_score=round(dom_score, 1),
        emotion_scores=emotion_scores,
        face_confidence=round(float(primary.get("face_confidence", 0.0) or 0.0), 3),
        region=FaceRegion(
            x=int(reg.get("x", 0)),
            y=int(reg.get("y", 0)),
            w=int(reg.get("w", 0)),
            h=int(reg.get("h", 0)),
        ),
        composure_instant=composure_instant,
        timestamp=timestamp,
    )


def count_filler_words(transcript_text: str) -> tuple[int, dict[str, int]]:
    """
    Dem cac tu dem ngap ngung trong tieng Viet ("ờ", "ừm", "kiểu", "à", "ừ", "um", "uh")
    theo ranh gioi tu (word/token boundary) de khong dem nham "à" trong "là", "và", "nhà".
    """
    if not transcript_text or not transcript_text.strip():
        return 0, {}

    tokens = re.findall(r"[\wÀ-ỹ]+", transcript_text.lower(), flags=re.UNICODE)
    counts: dict[str, int] = {}
    for fw in FILLER_WORDS:
        c = sum(1 for t in tokens if t == fw)
        if c > 0:
            counts[fw] = c

    total_fillers = sum(counts.values())
    return total_fillers, counts


def compute_voice_metrics_from_text(transcript_text: str, duration_seconds: float) -> VoiceMetrics:
    """Tinh WPM, Pace Evaluation, Pace Score, Filler Count va Fluency Score tu transcript."""
    clean_text = (transcript_text or "").strip()
    words = clean_text.split() if clean_text else []
    word_count = len(words)

    effective_duration = float(duration_seconds) if duration_seconds and duration_seconds > 0 else 0.0
    if effective_duration <= 0.0 and word_count > 0:
        # Neu khong truyen thoi luong, uoc luong theo toc do noi trung binh 130 WPM
        effective_duration = max(5.0, (word_count / 130.0) * 60.0)

    if word_count == 0:
        return VoiceMetrics(
            transcript_text="",
            duration_seconds=round(effective_duration, 1),
            word_count=0,
            wpm=0.0,
            pace_evaluation="Không có giọng nói",
            pace_score=50.0,
            filler_count=0,
            filler_words_found={},
            fluency_score=100.0,
        )

    duration_minutes = max(effective_duration / 60.0, 0.05)
    wpm = round(word_count / duration_minutes, 1)

    if wpm > 170:
        pace_evaluation = "Nhanh (Cần kiểm soát lại)"
    elif wpm >= 110:
        pace_evaluation = "Chuẩn tranh biện (110-170 WPM)"
    elif wpm > 40:
        pace_evaluation = "Khá chậm / Ngập ngừng"
    else:
        pace_evaluation = "Rất ít từ / Quá chậm"

    if 110 <= wpm <= 170:
        pace_score = 100.0
    elif 80 <= wpm < 110 or 170 < wpm <= 200:
        pace_score = 80.0
    else:
        pace_score = 50.0

    filler_count, filler_breakdown = count_filler_words(clean_text)
    fluency_score = float(max(0, 100 - (filler_count * 15)))

    return VoiceMetrics(
        transcript_text=clean_text,
        duration_seconds=round(effective_duration, 1),
        word_count=word_count,
        wpm=wpm,
        pace_evaluation=pace_evaluation,
        pace_score=pace_score,
        filler_count=filler_count,
        filler_words_found=filler_breakdown,
        fluency_score=fluency_score,
    )


def transcribe_audio_bytes(audio_bytes: bytes, file_suffix: str = ".wav") -> tuple[str, float]:
    """
    Chay Faster-Whisper de chuyen giong noi thanh van ban tieng Viet.
    Tra ve (transcript_text, detected_duration_seconds).
    """
    ensure_models_loaded(load_whisper=True)
    if _whisper_model is None:
        logger.warning("Whisper model is not available; returning empty transcript.")
        return "", 0.0

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_suffix) as tmp_file:
            tmp_file.write(audio_bytes)
            tmp_path = tmp_file.name

        segments, info = _whisper_model.transcribe(
            tmp_path,
            language="vi",
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
            initial_prompt="Kính thưa ban giám khảo, tôi xin trình bày luận điểm tranh biện:",
        )
        texts = [seg.text for seg in segments]
        transcript_text = " ".join(texts).strip()
        audio_duration = float(getattr(info, "duration", 0.0) or 0.0)
        return transcript_text, audio_duration
    except Exception as exc:
        logger.error("Loi khi transcribe am thanh bang Faster-Whisper: %s", exc)
        return "", 0.0
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def generate_report_chart_base64(
    overall_score: float,
    voice: VoiceMetrics,
    facial: FacialMetrics,
) -> Optional[str]:
    """
    Ve bieu do bao cao truc quan (Facial Emotion Distribution Pie Chart + Multimodal Summary Box)
    giong debate_session_analyzer.py va tra ve chuoi data:image/png;base64,...
    """
    try:
        plt.style.use(
            "seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default"
        )
        fig, axs = plt.subplots(1, 2, figsize=(14, 6))
        fig.suptitle(
            f"AI Multimodal Debate Evaluation Report (Score: {overall_score:.1f}/100)",
            fontsize=16,
            fontweight="bold",
        )

        labels = [k.capitalize() for k, v in facial.emotion_pct.items() if v > 0]
        sizes = [v for v in facial.emotion_pct.values() if v > 0]
        if sizes:
            colors = ["#4CAF50", "#2196F3", "#FFC107", "#E91E63", "#9C27B0", "#FF5722", "#607D8B"]
            axs[0].pie(
                sizes,
                labels=labels,
                autopct="%1.1f%%",
                startangle=140,
                colors=colors[: len(sizes)],
            )
        else:
            axs[0].text(0.5, 0.5, "No face detected", ha="center", va="center", fontsize=12)
        axs[0].set_title("Facial Emotion Distribution (DeepFace)", fontsize=13, fontweight="bold")

        axs[1].axis("off")
        preview = (
            f'"{voice.transcript_text[:120]}..."'
            if len(voice.transcript_text) > 120
            else f'"{voice.transcript_text or "(Không phát hiện lời nói)"}"'
        )
        summary_text = (
            f"--- MULTIMODAL DEBATE SUMMARY ---\n\n"
            f"• Duration: {voice.duration_seconds:.1f}s\n"
            f"• Words Spoken: {voice.word_count} words\n"
            f"• Speaking Rate: {voice.wpm:.1f} WPM ({voice.pace_evaluation})\n"
            f"• Filler / Hesitations: {voice.filler_count} times (Fluency: {voice.fluency_score:.0f}/100)\n"
            f"• Eye Contact Rate: {facial.eye_contact_rate:.1f}%\n"
            f"• Composure (Calmness): {facial.composure_score:.1f}%\n\n"
            f"---------------------------------\n"
            f"* OVERALL DEMEANOR SCORE: {overall_score:.1f} / 100\n"
            f"---------------------------------\n\n"
            f"Transcript Preview:\n{preview}"
        )
        axs[1].text(
            0.05,
            0.95,
            summary_text,
            fontsize=11.5,
            verticalalignment="top",
            bbox=dict(boxstyle="round,pad=1", facecolor="#F0F4F8", edgecolor="#3B82F6", linewidth=2),
        )

        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=160)
        plt.close(fig)
        buf.seek(0)
        b64_png = base64.b64encode(buf.read()).decode("utf-8")
        return f"data:image/png;base64,{b64_png}"
    except Exception as exc:
        logger.warning("Khong the tao report chart PNG: %s", exc)
        return None


def analyze_multimodal_turn(req: MultimodalTurnRequest) -> MultimodalTurnResult:
    """
    Phan tich toan dien 1 luot tranh bien:
    1. Neu co frames_base64 -> chay DeepFace.analyze tren tung frame de lay emotion_timeline
    2. Ket hop voi emotion_timeline truyen san (neu co)
    3. Neu co audio_base64 -> giai ma va chay Faster-Whisper de lay transcript_text
    4. Tinh toan VoiceMetrics, FacialMetrics va Overall Demeanor Score
    """
    timeline: list[EmotionSample] = list(req.emotion_timeline or [])
    total_frames = req.total_frames_captured or 0
    face_detected_frames = sum(1 for item in timeline if item.face_detected)

    # 1. Phan tich cac key-frames base64 bang DeepFace (neu Frontend gui len)
    if req.frames_base64:
        for idx, frame_b64 in enumerate(req.frames_base64):
            try:
                frame = decode_base64_image(frame_b64)
                frame_res = analyze_single_frame(frame, timestamp=float(idx))
                total_frames += 1
                if frame_res.face_detected:
                    face_detected_frames += 1
                    timeline.append(
                        EmotionSample(
                            time=float(idx),
                            dominant=frame_res.dominant_emotion,
                            scores=frame_res.emotion_scores,
                            face_detected=True,
                        )
                    )
            except Exception as exc:
                logger.debug("Bo qua frame %d do loi decode/analyze: %s", idx, exc)

    if total_frames < len(timeline):
        total_frames = len(timeline)

    # 2. Tinh toan Facial Emotion Metrics
    emotion_counts = {e: 0 for e in EMOTIONS}
    for item in timeline:
        if not item.face_detected:
            continue
        dom = item.dominant.lower().strip()
        # Map cac nhan tuong duong tu client-side neu co (surprised -> surprise, fearful -> fear, disgusted -> disgust)
        alias_map = {
            "surprised": "surprise",
            "fearful": "fear",
            "disgusted": "disgust",
        }
        dom = alias_map.get(dom, dom)
        if dom in emotion_counts:
            emotion_counts[dom] += 1

    total_emotion_samples = sum(emotion_counts.values())
    if total_emotion_samples > 0:
        emotion_pct = {
            k: round((v / total_emotion_samples) * 100.0, 1) for k, v in emotion_counts.items()
        }
        dominant_overall = max(emotion_counts, key=emotion_counts.get)
        composure_score = round(
            min(100.0, emotion_pct.get("neutral", 0.0) + emotion_pct.get("happy", 0.0)), 1
        )
        eye_contact_rate = (
            round((face_detected_frames / max(total_frames, 1)) * 100.0, 1)
            if total_frames > 0
            else 100.0
        )
    else:
        emotion_pct = {e: (100.0 if e == "neutral" else 0.0) for e in EMOTIONS}
        dominant_overall = "neutral"
        composure_score = 80.0  # Mac dinh khi khong bat cam hoac khong co mau
        eye_contact_rate = 0.0

    facial_metrics = FacialMetrics(
        total_frames_analyzed=total_frames,
        face_detected_frames=face_detected_frames,
        eye_contact_rate=eye_contact_rate,
        dominant_emotion=dominant_overall,
        composure_score=composure_score,
        emotion_counts=emotion_counts,
        emotion_pct=emotion_pct,
    )

    # 3. Phan tich am thanh bang Faster-Whisper (hoac dung transcript_override)
    transcript_text = ""
    audio_duration = req.duration_seconds or 0.0

    if req.audio_base64:
        try:
            raw_audio_b64 = req.audio_base64.strip()
            suffix = ".wav"
            if raw_audio_b64.startswith("data:"):
                header, raw_audio_b64 = raw_audio_b64.split(",", 1)
                if "webm" in header:
                    suffix = ".webm"
                elif "ogg" in header:
                    suffix = ".ogg"
                elif "mp3" in header or "mpeg" in header:
                    suffix = ".mp3"
            audio_bytes = base64.b64decode(raw_audio_b64)
            stt_text, detected_dur = transcribe_audio_bytes(audio_bytes, file_suffix=suffix)
            if stt_text:
                transcript_text = stt_text
            if audio_duration <= 0 and detected_dur > 0:
                audio_duration = detected_dur
        except Exception as exc:
            logger.error("Loi giai ma audio_base64: %s", exc)

    if req.transcript_override and req.transcript_override.strip():
        # Neu Whisper khong bat duoc (hoac user sua/nhap tay), dung transcript_override
        if not transcript_text:
            transcript_text = req.transcript_override.strip()

    voice_metrics = compute_voice_metrics_from_text(transcript_text, audio_duration)

    # 4. Tinh DIEM PHONG THAI TONG THE (OVERALL DEMEANOR SCORE)
    # Cong thuc tu debate_session_analyzer.py: 0.4 * Composure + 0.3 * Pace + 0.3 * Fluency
    overall_demeanor_score = round(
        (0.4 * facial_metrics.composure_score)
        + (0.3 * voice_metrics.pace_score)
        + (0.3 * voice_metrics.fluency_score),
        1,
    )

    delivery_payload = DeliveryAnalyticsPayload(
        dominant_emotion=facial_metrics.dominant_emotion,
        eye_contact_rate=facial_metrics.eye_contact_rate,
        composure_score=facial_metrics.composure_score,
        confidence_score=round(
            min(100.0, max(10.0, 0.6 * facial_metrics.composure_score + 0.4 * voice_metrics.fluency_score)),
            1,
        ),
        wpm=voice_metrics.wpm,
        pace_evaluation=voice_metrics.pace_evaluation,
        pace_score=voice_metrics.pace_score,
        filler_count=voice_metrics.filler_count,
        fluency_score=voice_metrics.fluency_score,
        overall_demeanor_score=overall_demeanor_score,
        emotion_breakdown=facial_metrics.emotion_pct,
    )

    chart_b64 = None
    if req.include_report_chart:
        chart_b64 = generate_report_chart_base64(
            overall_demeanor_score, voice_metrics, facial_metrics
        )

    return MultimodalTurnResult(
        overall_demeanor_score=overall_demeanor_score,
        voice=voice_metrics,
        facial=facial_metrics,
        delivery_analytics=delivery_payload,
        report_chart_base64=chart_b64,
    )
