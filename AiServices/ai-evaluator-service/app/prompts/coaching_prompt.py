"""
Prompt builder cho Coaching (Argument-level va Round-level): goi y SAU KHI da cham.

Muc dich: learner da biet minh yeu o dau (tu ket qua /evaluate hoac
/evaluate/round), can biet LAM THE NAO de sua — (1) phuong phap cai thien cho
cac tieu chi yeu, (2) huong phat trien chinh y learner da neu. Ca 2 cap dung
chung 1 system prompt (_build_coaching_system_prompt), chi khac doi tuong
(1 luot noi / ca 1 round) va phan bai goc trong user prompt.

Nguyen tac thiet ke:
- Danh sach tieu chi can goi y do CODE chon (app/services/coaching.py), LLM chi
  giai thich — cung tinh than muc 3.8 trong docs/AI_DEVELOPMENT_LOG.md.
- KHONG viet lai bai thay learner (giu nguyen tac "khong bai mau chuan" —
  DEBO/Themis, xem docstring evaluator_prompt.py).
- KHONG bia so lieu/nguon cu the — chi mo ta LOAI dan chung nen tim (muc 2.5
  "khong fact-check" + lich su hallucination muc 3.4).
- Tai su dung ArgumentContext (SOLO/INTERACTIVE) de mo ta tieu chi dung ngu
  canh: bai khong co doi phuong thi khong goi y "phan bien doi phuong".
"""
from app.prompts.evaluator_prompt import (
    ArgumentContext,
    _rubric_as_text,
    _rubric_for_context,
    build_user_prompt,
    infer_argument_context,
)
from app.prompts.round_prompt import build_round_user_prompt, infer_round_context
from app.schemas import ArgumentCoachingRequest, CriterionScore, RoundCoachingRequest

_ARGUMENT_SUBJECT = "lap luan cua chinh ho"
_ROUND_SUBJECT = (
    "TOAN BO 1 round (giai doan) tranh bien cua chinh ho, xet tren tat ca cac luot "
    "noi cua learner trong round"
)

# Round CO luot doi phuong -> them yeu cau goi y cach phan hoi doi phuong tot
# hon. Round SOLO -> KHONG nhac gi den doi phuong (tranh AI bia ra 1 doi thu
# khong ton tai — xem docs/AI_DEVELOPMENT_LOG.md muc 3.4).
_ROUND_INTERACTION_TASK_BY_CONTEXT: dict[ArgumentContext, str] = {
    ArgumentContext.INTERACTIVE: (
        "   - Round nay CO luot cua doi phuong: trong \"application\", neu phu hop, chi ra "
        "learner nen phan hoi luot nao cua doi phuong tot hon va bang cach nao.\n"
    ),
    ArgumentContext.SOLO: "",
}


def _build_coaching_system_prompt(rubric_text: str, subject: str, extra_task: str = "") -> str:
    return f"""Ban la huan luyen vien tranh bien, giup 1 nguoi tranh bien (learner) CAI \
THIEN {subject}, dua tren ket qua cham diem DA CO san.

TOAN BO noi dung tra ve PHAI viet bang TIENG VIET. Chi rieng ten cac field JSON \
va ten tieu chi (Logic, Evidence, Relevance, Structure, Persuasiveness) giu \
nguyen tieng Anh.

[TIEU CHI DANH GIA - de hieu dung y nghia tung tieu chi]
{rubric_text}

[NHIEM VU]
1. Voi TUNG tieu chi trong danh sach [TIEU CHI CAN GOI Y] (o phan noi dung ben \
duoi) — DUNG va DU cac tieu chi do, DUNG thu tu, KHONG them tieu chi khac:
   - "diagnosis": chi ra van de cu the cua tieu chi nay trong CHINH bai nay \
(dua tren nhan xet da cham).
   - "methods": 2-3 ky thuat/phuong phap CU THE, ap dung duoc ngay de cai thien \
tieu chi nay.
   - "application": goi y cach ap dung cac phuong phap tren vao CHINH bai nay \
(chi ra nen bo sung gi, o cho nao).
{extra_task}2. "idea_development": giup learner PHAT TRIEN CHINH luan diem ho da neu:
   - "core_claim": tom tat 1 cau luan diem chinh learner da neu.
   - "directions": 2-4 huong dao sau luan diem do (vi du: giai thich co che \
vi sao dieu do xay ra, tac dong den ai va o muc do nao, so sanh voi phuong an \
nguoc lai...).
   - "evidence_to_look_for": cac LOAI dan chung nen tim de ho tro luan diem.

[RANG BUOC BAT BUOC]
- KHONG viet lai bai, KHONG viet doan van mau thay learner — chi goi y huong \
de learner TU viet.
- KHONG bia so lieu, ty le phan tram, ten nghien cuu, ten to chuc, nam hay \
nguon cu the. KHONG neu ten quoc gia/thanh pho/su kien cu the nhu la vi du \
"da xay ra" (vi du KHONG viet "cac thanh pho nhu X, Y da ap dung chinh sach \
nay") — nhung khang dinh do co the sai. Chi mo ta LOAI dan chung (vi du: "so \
lieu thong ke ve ty le ... tu co quan y te", "nghien cuu so sanh truoc/sau ...", \
"case study tu cac do thi da ap dung chinh sach tuong tu"), de learner tu tim \
va kiem chung.
- Rang buoc tren ap dung CA KHI dua vi du minh hoa: KHONG viet kieu "vi du: ty \
le tang 30% ..." hay "vi du: 2 gio/ngay ...". Neu can minh hoa thi de trong \
con so (vi du "ty le ...% nguoi dung ...") hoac mo ta dinh tinh. CHI duoc nhac \
lai con so DA CO SAN trong bai cua learner.
- KHONG cham lai, KHONG ban ve diem so — diem da duoc chot o buoc cham.
- Bam sat noi dung learner THUC SU da viet, KHONG gan cho learner y ho khong noi.

[OUTPUT - CHI tra ve JSON hop le, khong them text nao khac ngoai JSON]
{{
  "focus_criteria": [
    {{"name": "<ten tieu chi>", "diagnosis": "<...>", "methods": ["<...>", "..."], "application": "<...>"}}
  ],
  "idea_development": {{
    "core_claim": "<...>",
    "directions": ["<...>", "..."],
    "evidence_to_look_for": ["<...>", "..."]
  }}
}}"""


def _build_coaching_user_prompt(
    original_text: str,
    criteria: list[CriterionScore],
    summary_label: str,
    summary: str,
    weaknesses: list[str],
    focus_names: list[str],
) -> str:
    """original_text la phan bai goc dung lai DUNG nhu luc cham (KHONG dua
    raw_model_output vao)."""
    criteria_lines = [f"- {c.name} ({c.score}/5): {c.reasoning}" for c in criteria]
    weaknesses_text = "; ".join(weaknesses) if weaknesses else "khong co"
    parts = [
        original_text,
        "[KET QUA CHAM DA CO]\n"
        + "\n".join(criteria_lines)
        + f"\n{summary_label}: {summary}"
        + f"\nDiem yeu: {weaknesses_text}",
        "[TIEU CHI CAN GOI Y - dung va du, dung thu tu]\n" + ", ".join(focus_names),
    ]
    return "\n\n".join(parts)


def build_coaching_prompt(req: ArgumentCoachingRequest, focus_names: list[str]) -> tuple[str, str]:
    """Argument-level. Tra ve (system_prompt, user_prompt). Mo ta tieu chi dung
    theo ArgumentContext suy ra tu req.request (co/khong opponent_argument_text)."""
    context = infer_argument_context(req.request)
    rubric_text = _rubric_as_text(_rubric_for_context(context))
    evaluation = req.evaluation
    user_prompt = _build_coaching_user_prompt(
        build_user_prompt(req.request),
        evaluation.criteria,
        "Nhan xet tong hop",
        evaluation.overall_reasoning,
        evaluation.weaknesses,
        focus_names,
    )
    return _build_coaching_system_prompt(rubric_text, _ARGUMENT_SUBJECT), user_prompt


def build_round_coaching_prompt(req: RoundCoachingRequest, focus_names: list[str]) -> tuple[str, str]:
    """Round-level. Context suy tu req.request.turns (co/khong luot OPPONENT) —
    tai su dung infer_round_context cua round_prompt.py."""
    context = infer_round_context(req.request)
    rubric_text = _rubric_as_text(_rubric_for_context(context))
    evaluation = req.evaluation
    user_prompt = _build_coaching_user_prompt(
        build_round_user_prompt(req.request),
        evaluation.criteria,
        "Nhan xet tinh nhat quan xuyen suot round",
        evaluation.consistency_note,
        evaluation.weaknesses,
        focus_names,
    )
    system_prompt = _build_coaching_system_prompt(
        rubric_text, _ROUND_SUBJECT, _ROUND_INTERACTION_TASK_BY_CONTEXT[context]
    )
    return system_prompt, user_prompt
