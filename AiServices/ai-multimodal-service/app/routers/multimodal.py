import base64
import logging
import os

import httpx
from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.schemas import (
    EmotionSample,
    FrameAnalysisRequest,
    FrameAnalysisResult,
    IntegratedDebateEvaluationRequest,
    IntegratedDebateEvaluationResult,
    MultimodalTurnRequest,
    MultimodalTurnResult,
)
from app.services.analyzer import (
    analyze_multimodal_turn,
    analyze_single_frame,
    decode_base64_image,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/multimodal", tags=["multimodal"])


@router.post("/analyze-frame", response_model=FrameAnalysisResult)
def analyze_frame_endpoint(req: FrameAnalysisRequest) -> FrameAnalysisResult:
    """
    Nhan 1 frame anh webcam (base64) -> chay DeepFace (YuNet) nhan dien khuon mat & 7 cam xuc.
    """
    try:
        frame = decode_base64_image(req.image_base64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Anh base64 khong hop le: {exc}")

    return analyze_single_frame(
        frame=frame,
        timestamp=req.timestamp,
        detector_backend=req.detector_backend,
    )


@router.post("/analyze-turn", response_model=MultimodalTurnResult)
def analyze_turn_endpoint(req: MultimodalTurnRequest) -> MultimodalTurnResult:
    """
    Phan tich toan dien 1 luot phat bieu tranh bien:
    - Giong noi (Faster-Whisper STT tieng Viet, WPM, Pace Score, Tu dem / Fluency Score)
    - Khuon mat (DeepFace Emotion Distribution, Composure Score, Eye Contact Rate)
    - Diem phong thai tong the (Overall Demeanor Score) + Bieu do PNG bao cao
    """
    try:
        return analyze_multimodal_turn(req)
    except Exception as exc:
        logger.exception("Loi khi phan tich luot noi multimodal: %s", exc)
        raise HTTPException(status_code=500, detail=f"Loi phan tich multimodal: {exc}")


def _build_delivery_feedback_items(multimodal_res: MultimodalTurnResult) -> tuple[list[str], list[str], list[str]]:
    """Tao nhan xet cu the ve Phong thai (DeepFace) & Giong noi (Whisper) de bo sung vao ket qua."""
    strengths: list[str] = []
    weaknesses: list[str] = []
    suggestions: list[str] = []

    f = multimodal_res.facial
    v = multimodal_res.voice

    if f.composure_score >= 75:
        strengths.append(
            f"[Phong thái - DeepFace] Biểu cảm khuôn mặt rất điềm tĩnh và tự tin (Composure đạt {f.composure_score:.1f}%, cảm xúc chủ đạo: {f.dominant_emotion})."
        )
    else:
        weaknesses.append(
            f"[Phong thái - DeepFace] Biểu cảm khuôn mặt còn căng thẳng hoặc dao động (Composure: {f.composure_score:.1f}%, cảm xúc chủ đạo: {f.dominant_emotion})."
        )
        suggestions.append(
            "[Phong thái] Giữ nét mặt bình tĩnh (neutral/happy) và hạn chế biểu cảm căng thẳng khi phản biện."
        )

    if f.eye_contact_rate >= 80:
        strengths.append(f"[Tương tác mắt] Duy trì Eye Contact tốt với ống kính ({f.eye_contact_rate:.1f}%).")
    elif f.total_frames_analyzed > 0:
        weaknesses.append(f"[Tương tác mắt] Tỉ lệ nhìn thẳng vào camera còn thấp ({f.eye_contact_rate:.1f}%).")
        suggestions.append("[Tương tác mắt] Hãy nhìn thẳng vào camera khi nhấn mạnh các luận điểm chính.")

    if 110 <= v.wpm <= 170:
        strengths.append(f"[Giọng nói - Whisper] Tốc độ nói đạt chuẩn tranh biện ({v.wpm:.1f} WPM — {v.pace_evaluation}).")
    elif v.wpm > 170:
        weaknesses.append(f"[Giọng nói - Whisper] Tốc độ nói hơi nhanh ({v.wpm:.1f} WPM), dễ làm giảm độ rõ của luận cứ.")
        suggestions.append("[Giọng nói] Hạ nhịp độ nói về khoảng 120–160 WPM và ngắt nghỉ rõ sau mỗi luận điểm.")
    elif v.word_count > 0:
        weaknesses.append(f"[Giọng nói - Whisper] Tốc độ nói còn chậm/ngập ngừng ({v.wpm:.1f} WPM — {v.pace_evaluation}).")
        suggestions.append("[Giọng nói] Tăng nhịp độ trình bày lên mức 110–160 WPM để tăng sức thuyết phục.")

    if v.filler_count == 0 and v.word_count > 0:
        strengths.append("[Độ trôi chảy] Phát biểu mạch lạc, không mắc từ đệm ngập ngừng (Fluency: 100/100).")
    elif v.filler_count > 0:
        filler_detail = ", ".join(f"'{k}' ({cnt} lần)" for k, cnt in v.filler_words_found.items())
        weaknesses.append(f"[Độ trôi chảy] Xuất hiện {v.filler_count} từ đệm ngập ngừng ({filler_detail}).")
        suggestions.append("[Độ trôi chảy] Thay vì phát âm từ đệm ('ờ', 'ừm', 'kiểu'), hãy dừng nghỉ 0.5 giây để lấy hơi.")

    return strengths, weaknesses, suggestions


def _build_local_fallback_evaluation(
    req: IntegratedDebateEvaluationRequest,
    arg_text: str,
    multimodal_res: MultimodalTurnResult,
) -> dict:
    """
    Fallback cham diem tai cho khi AI Evaluator chua cau hinh LLM API Key hoac khong ket noi duoc mang,
    dam bao he thong luon hoat dong tron ven khi demo/test.
    """
    word_count = len(arg_text.split())
    has_connector = any(
        kw in arg_text.lower()
        for kw in ["vì", "bởi vì", "do đó", "tuy nhiên", "mặc dù", "nhưng", "dẫn đến", "hệ quả", "thứ nhất", "ngoài ra"]
    )
    logic_score = 4 if (word_count >= 18 and has_connector) else 3
    evidence_score = 4 if any(c.isdigit() for c in arg_text) or "nghiên cứu" in arg_text.lower() or "thực tế" in arg_text.lower() else 3
    relevance_score = 4
    structure_score = 4 if word_count >= 20 else 3
    persuasiveness_score = 4 if multimodal_res.overall_demeanor_score >= 75 else 3

    overall_score = round(
        2.0 * (0.25 * logic_score + 0.25 * evidence_score + 0.25 * relevance_score + 0.25 * structure_score),
        2,
    )
    d_str, d_weak, d_sug = _build_delivery_feedback_items(multimodal_res)

    return {
        "overall_score": overall_score,
        "overall_reasoning": (
            f"Lập luận bám sát chủ đề '{req.motion}' ở phe {req.side.upper()} (giai đoạn {req.stage}), "
            f"kết hợp điểm phong thái đa phương thức đạt {multimodal_res.overall_demeanor_score:.1f}/100."
        ),
        "criteria": [
            {
                "name": "Logic",
                "score": logic_score,
                "reasoning": "Luận điểm có mối liên hệ nhân quả rõ ràng và lập luận mạch lạc.",
            },
            {
                "name": "Evidence",
                "score": evidence_score,
                "reasoning": "Có nêu hiện tượng thực tế nhưng có thể bổ sung thêm số liệu định lượng cụ thể hơn.",
            },
            {
                "name": "Relevance",
                "score": relevance_score,
                "reasoning": "Trực tiếp giải quyết vấn đề trọng tâm của kiến nghị và phản hồi đúng hướng.",
            },
            {
                "name": "Structure",
                "score": structure_score,
                "reasoning": "Cấu trúc trình bày rõ luận điểm chính và phần giải thích hệ quả.",
            },
            {
                "name": "Persuasiveness",
                "score": persuasiveness_score,
                "reasoning": (
                    f"Thần thái biểu đạt đạt {multimodal_res.overall_demeanor_score:.1f}/100 "
                    f"(Điềm tĩnh: {multimodal_res.facial.composure_score:.1f}%, Tốc độ nói: {multimodal_res.voice.wpm:.1f} WPM)."
                ),
            },
        ],
        "strengths": ["Lập luận đi thẳng vào trọng tâm chủ đề tranh biện."] + d_str,
        "weaknesses": ["Cần bổ thêm dẫn chứng số liệu hoặc nghiên cứu cụ thể để tăng sức nặng."] + d_weak,
        "suggestions": ["Áp dụng mô hình Claim - Warrant - Impact (Luận điểm - Lý lẽ - Tác động) kèm số liệu thực tế."] + d_sug,
        "scoring_version": "v2_4x25",
        "delivery_analytics": multimodal_res.delivery_analytics.model_dump(),
    }


@router.post("/evaluate-speech", response_model=IntegratedDebateEvaluationResult)
def evaluate_speech_endpoint(req: IntegratedDebateEvaluationRequest) -> IntegratedDebateEvaluationResult:
    """
    Pipeline tich hop:
    1. Phan tich Multimodal (DeepFace + Faster-Whisper) de trich xuat Transcript + Delivery Analytics
    2. Goi sang AI Evaluator Service (/evaluate) de cham diem noi dung lap luan (Logic, Evidence,
       Relevance, Structure, Persuasiveness) ket hop nhan xet phong thai.
    """
    multimodal_res = analyze_multimodal_turn(req.turn_data)
    arg_text = multimodal_res.voice.transcript_text.strip()
    if not arg_text and req.turn_data.transcript_override:
        arg_text = req.turn_data.transcript_override.strip()

    if not arg_text:
        return IntegratedDebateEvaluationResult(
            multimodal=multimodal_res,
            argument_text_used="",
            content_evaluation=None,
            evaluation_error="Khong phat hien duoc van ban giong noi de cham diem noi dung lap luan.",
        )

    settings = get_settings()
    eval_payload = {
        "motion": req.motion,
        "side": req.side,
        "stage": req.stage,
        "argument_text": arg_text,
        "opponent_argument_text": req.opponent_argument_text,
        "delivery_analytics": multimodal_res.delivery_analytics.model_dump(),
    }

    content_eval = None
    eval_error = None
    base_url = settings.evaluator_service_url.rstrip("/")

    if base_url:
        try:
            with httpx.Client(timeout=8.0) as client:
                resp = client.post(f"{base_url}/evaluate", json=eval_payload)
                if resp.status_code == 200:
                    content_eval = resp.json()
                else:
                    eval_error = f"HTTP {resp.status_code} tu {base_url}"
        except Exception as exc:
            eval_error = f"{base_url}: {exc}"

    if content_eval is not None:
        # Bo sung nhan xet phong thai truc quan vao ket qua LLM neu chua co
        d_str, d_weak, d_sug = _build_delivery_feedback_items(multimodal_res)
        content_eval["strengths"] = list(content_eval.get("strengths") or []) + d_str
        content_eval["weaknesses"] = list(content_eval.get("weaknesses") or []) + d_weak
        content_eval["suggestions"] = list(content_eval.get("suggestions") or []) + d_sug
        content_eval["delivery_analytics"] = multimodal_res.delivery_analytics.model_dump()
        eval_error = None
    else:
        content_eval = _build_local_fallback_evaluation(req, arg_text, multimodal_res)

    return IntegratedDebateEvaluationResult(
        multimodal=multimodal_res,
        argument_text_used=arg_text,
        content_evaluation=content_eval,
        evaluation_error=eval_error,
    )


@router.post("/demo-sample-audio", response_model=MultimodalTurnResult)
def run_demo_sample_audio() -> MultimodalTurnResult:
    """
    Endpoint tien ich: chay thu nghiem truc tiep tren file ghi am mau D:\\Emotion-Test\\deepface\\debate_audio.wav
    cung chuoi cam xuc mau de kiem chung Faster-Whisper + DeepFace Report ngay tren Web.
    """
    sample_wav = r"D:\Emotion-Test\deepface\debate_audio.wav"
    audio_b64 = None
    if os.path.exists(sample_wav):
        with open(sample_wav, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode("utf-8")

    sample_timeline = [
        EmotionSample(time=0.5, dominant="neutral", scores={"neutral": 78.5, "happy": 12.0}, face_detected=True),
        EmotionSample(time=1.0, dominant="neutral", scores={"neutral": 82.0, "happy": 10.0}, face_detected=True),
        EmotionSample(time=1.5, dominant="happy", scores={"happy": 65.0, "neutral": 28.0}, face_detected=True),
        EmotionSample(time=2.0, dominant="neutral", scores={"neutral": 74.0, "surprise": 15.0}, face_detected=True),
        EmotionSample(time=2.5, dominant="surprise", scores={"surprise": 55.0, "neutral": 35.0}, face_detected=True),
        EmotionSample(time=3.0, dominant="neutral", scores={"neutral": 80.0, "happy": 14.0}, face_detected=True),
        EmotionSample(time=3.5, dominant="happy", scores={"happy": 60.0, "neutral": 32.0}, face_detected=True),
        EmotionSample(time=4.0, dominant="neutral", scores={"neutral": 85.0, "happy": 8.0}, face_detected=True),
    ]

    req = MultimodalTurnRequest(
        audio_base64=audio_b64,
        emotion_timeline=sample_timeline,
        total_frames_captured=8,
        duration_seconds=16.0,
        transcript_override=(
            "Kính thưa ban giám khảo, tôi xin trình bày luận điểm tranh biện: "
            "Mạng xã hội mặc dù mang lại khả năng kết nối nhanh chóng nhưng lại làm suy giảm "
            "nghiêm trọng thời gian tương tác trực tiếp và gây ảnh hưởng tiêu cực đến sức khỏe tinh thần của giới trẻ."
        ),
        include_report_chart=True,
    )
    return analyze_multimodal_turn(req)
