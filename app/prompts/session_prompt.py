"""
Prompt builder cho Session-level report.

Diem tong (overall_score) va diem tung giai doan (stage_breakdown) duoc tinh
TOAN HOC trong session_evaluator.py (trung binh cac round_score da co san),
KHONG goi LLM cham lai — vi cac round da duoc cham roi, cham lai se ton chi
phi va co the ra ket qua khac (thieu nhat quan). LLM CHI duoc dung de tong
hop phan nhan xet dinh tinh (progress_trend, overall_strengths/weaknesses/
suggestions) tu cac ket qua round da co, giup bao cao doc de hieu hon la
liet ke rieng le tung round.
"""
from app.schemas import SessionEvaluationRequest

SIDE_LABEL = {
    "pro": "Ung ho (Pro)",
    "con": "Phan doi (Con)",
}

STAGE_LABEL = {
    "opening": "Mo dau",
    "rebuttal": "Phan bien",
    "closing": "Ket luan",
}


SESSION_SYSTEM_PROMPT = """Ban la mot huan luyen vien tranh bien, tong hop bao cao cuoi \
phien cho 1 learner dua tren ket qua cham diem TUNG ROUND da co san (khong can cham lai \
diem so, chi tong hop nhan xet).

TOAN BO PHAN NHAN XET PHAI viet bang TIENG VIET.

[NHIEM VU]
Doc ket qua cham diem cua tat ca cac round (da kem diem so, diem manh/yeu, goi y cua \
tung round), roi tong hop thanh 1 bao cao TONG QUAN cho ca phien:
1. Nhan xet XU HUONG tien bo hay giam sut qua cac giai doan (vi du: hoc vien bat dau \
yeu o Opening nhung cai thien ro ret o Rebuttal).
2. Rut ra 2-4 DIEM MANH chung, xuyen suot nhieu round (khong lap lai y tung round rieng le).
3. Rut ra 2-4 DIEM YEU chung, xuyen suot nhieu round.
4. Dua ra 2-4 GOI Y cu the, uu tien nhung gi anh huong lon nhat den ket qua, de learner \
tap trung cai thien cho phien luyen tap tiep theo.

[OUTPUT - CHI tra ve JSON hop le, khong them text nao khac ngoai JSON]
{
  "progress_trend": "<nhan xet xu huong qua cac giai doan, tieng Viet>",
  "overall_strengths": ["<diem manh chung 1>", "..."],
  "overall_weaknesses": ["<diem yeu chung 1>", "..."],
  "overall_suggestions": ["<goi y cu the cho phien sau>", "..."]
}"""


def build_session_user_prompt(req: SessionEvaluationRequest) -> str:
    side_label = SIDE_LABEL.get(req.side.value, req.side.value.upper())

    round_summaries = []
    for r in req.rounds:
        stage_label = STAGE_LABEL.get(r.stage.value, r.stage.value)
        round_summaries.append(
            f"--- Round: {stage_label} (round_score = {r.round_score}/10) ---\n"
            f"Tinh nhat quan: {r.consistency_note}\n"
            f"Diem manh: {'; '.join(r.strengths) if r.strengths else 'khong co'}\n"
            f"Diem yeu: {'; '.join(r.weaknesses) if r.weaknesses else 'khong co'}\n"
            f"Goi y: {'; '.join(r.suggestions) if r.suggestions else 'khong co'}"
        )

    parts = [
        f"[MOTION]\n{req.motion}",
        f"[PHIA CUA LEARNER] {side_label}",
        "[KET QUA TUNG ROUND]\n\n" + "\n\n".join(round_summaries),
    ]
    return "\n\n".join(parts)


def build_session_evaluation_prompt(req: SessionEvaluationRequest) -> tuple[str, str]:
    """Tra ve (system_prompt, user_prompt), san sang goi LLM."""
    return SESSION_SYSTEM_PROMPT, build_session_user_prompt(req)
