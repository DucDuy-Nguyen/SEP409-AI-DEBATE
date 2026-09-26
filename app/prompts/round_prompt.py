"""
Prompt builder cho Round-level evaluation.

Khac voi Argument-level (cham 1 luot noi don le), Round-level cham TOAN BO 1
giai doan (vi du: het phan Rebuttal), gom nhieu luot noi qua lai giua learner
va doi phuong. Diem khong phai trung binh don gian cua tung luot — LLM duoc
yeu cau danh gia THEM tinh nhat quan xuyen suot round (co giu vung lap truong,
co phan ung tot voi phan bien cua doi phuong qua tung luot khong).

Dung lai dung 5 tieu chi + thang diem 5 bac + cong thuc quy doi thang 10 nhu
app/prompts/evaluator_prompt.py, de dam bao nhat quan giua 2 cap do cham diem.

GHI CHU (2026-09, DA SUA): Argument-level (evaluator_prompt.py) suy ra
ArgumentContext (SOLO/INTERACTIVE) tu req.opponent_argument_text de doi mo ta
Relevance khi khong co doi phuong. Round-level TRUOC DAY dung cung RUBRIC goc
(tuong duong INTERACTIVE) cho MOI round, ke ca round hoan toan khong co luot
OPPONENT nao trong turns — day chinh la nguyen nhan gay 2 case hallucination
da ghi trong docs/AI_DEVELOPMENT_LOG.md muc 3.4 (S01, S03: ca 2 deu la round
Closing chi co 1 luot noi cua learner, AI bi "thieu ngu canh" nen bia noi dung
khi cham Relevance theo mo ta yeu cau "phan bien doi phuong" khong ton tai).

DA AP DUNG lai co che ArgumentContext cho Round-level: infer_round_context()
ben duoi suy ra INTERACTIVE neu turns co it nhat 1 luot TurnSpeaker.OPPONENT,
nguoc lai SOLO. Tai su dung TRUC TIEP ArgumentContext va _rubric_for_context()
tu evaluator_prompt.py (khong copy-paste lai dict override hay logic chon
rubric) — build_round_evaluation_prompt() gio dung dung rubric (mo ta
Relevance) tuong ung voi context suy ra tu turns.

round_score (2026-09): Cung ap dung lai nguyen tac da chot cho overall_score
o Argument-level — round_score LUON tinh bang cong thuc, KHONG con hoi AI tu
dua ra 1 gia tri rieng (buoc 4 ben duoi va [OUTPUT] JSON da bo yeu cau nay).
Ly do: AI tung tra round_score=14.0 (vuot thang 0-10) gay ValidationError —
cung ban chat voi van de o Argument-level. Xem day du trong
docs/AI_DEVELOPMENT_LOG.md muc 3.8.
"""
from app.prompts.evaluator_prompt import ArgumentContext, GRADING_TIERS, _rubric_as_text, _rubric_for_context
from app.schemas import RoundEvaluationRequest, TurnSpeaker

STAGE_LABEL = {
    "opening": "Mo dau",
    "rebuttal": "Phan bien",
    "closing": "Ket luan",
}

SIDE_LABEL = {
    "pro": "Ung ho (Pro)",
    "con": "Phan doi (Con)",
}


def infer_round_context(req: RoundEvaluationRequest) -> ArgumentContext:
    """Suy ra ArgumentContext TU DU LIEU THUC TE cua round (turns co chua
    TurnSpeaker.OPPONENT hay khong) — tuong tu infer_argument_context() o
    Argument-level, nhung dua tren turns thay vi opponent_argument_text."""
    if any(t.speaker == TurnSpeaker.OPPONENT for t in req.turns):
        return ArgumentContext.INTERACTIVE
    return ArgumentContext.SOLO


# Khac voi Argument-level (noi "doi phuong" CHI xuat hien trong mo ta tieu chi
# Relevance), prompt Round-level con nhac "doi phuong"/"phan bien" o CA cau mo
# dau va buoc kiem tra tinh nhat quan — neu chi doi mo ta Relevance qua
# _rubric_for_context() se KHONG du de loai bo hoan toan yeu cau "phan ung voi
# doi phuong" khoi 1 round SOLO (van con sot lai o 2 cho nay, van co the gay
# hallucination tuong tu case S01/S03). Vi vay dinh nghia them 2 doan text
# rieng theo context o day, dung CUNG mot pattern dict-tra-cuu nhu
# _CRITERION_OVERRIDES_BY_CONTEXT ben evaluator_prompt.py.
_ROUND_INTRO_BY_CONTEXT: dict[ArgumentContext, str] = {
    ArgumentContext.INTERACTIVE: (
        "danh gia TOAN BO mot round (giai doan) tranh bien cua 1 nguoi tranh bien (learner), "
        "dua tren tat ca cac luot noi qua lai voi doi phuong trong round nay."
    ),
    ArgumentContext.SOLO: (
        "danh gia TOAN BO mot round (giai doan) tranh bien cua 1 nguoi tranh bien (learner), "
        "dua tren toan bo cac luot noi cua learner trong round nay. CHI danh gia dung noi dung "
        "duoc cung cap ben duoi, KHONG duoc gia dinh hay bia them bat ky noi dung nao khac."
    ),
}

_ROUND_CONSISTENCY_STEP_BY_CONTEXT: dict[ArgumentContext, str] = {
    ArgumentContext.INTERACTIVE: (
        "2. Danh gia TINH NHAT QUAN: learner co giu vung lap truong xuyen suot khong, co "
        "phan ung/phan bien tot voi tung luot noi cua doi phuong khong, hay bi lung lay/doi y "
        "mot cach khong hop ly (day la loi sycophancy da duoc ghi nhan o cac he thong AI debate "
        "khac — CAN cham diem thap hon o Logic/Persuasiveness neu phat hien hien tuong nay)."
    ),
    ArgumentContext.SOLO: (
        "2. Danh gia TINH NHAT QUAN: learner co giu vung lap truong xuyen suot cac luot noi "
        "khong, co tu mau thuan voi chinh minh giua cac luot khong — chi danh gia su nhat quan "
        "NOI TAI trong chinh cac luot noi cua learner."
    ),
}


def _build_round_system_prompt(context: ArgumentContext) -> str:
    """Dung dung rubric (mo ta Relevance) VA dung doan intro/buoc kiem tra tinh
    nhat quan tuong ung voi ArgumentContext da suy ra tu turns cua round — xem
    infer_round_context(), _rubric_for_context() (tai su dung tu
    evaluator_prompt.py), va 2 dict o tren."""
    rubric_text = _rubric_as_text(_rubric_for_context(context))
    intro_text = _ROUND_INTRO_BY_CONTEXT[context]
    consistency_step_text = _ROUND_CONSISTENCY_STEP_BY_CONTEXT[context]

    return f"""Ban la giam khao tranh bien cong tam, {intro_text}

TOAN BO PHAN GIAI THICH, NHAN XET, GOI Y trong ket qua tra ve PHAI viet bang TIENG VIET. \
Chi rieng ten cac field JSON va ten 5 tieu chi (Logic, Evidence, Relevance, Structure, \
Persuasiveness) giu nguyen tieng Anh.

[TIEU CHI - trong so bang nhau, moi tieu chi chiem 20% diem tong]
{rubric_text}

[HE THONG CHAM DIEM 5 BAC - ap dung cho MOI tieu chi, xet tren TOAN BO round]
{GRADING_TIERS}

[QUY TRINH BAT BUOC]
1. Doc toan bo cac luot noi cua learner trong round theo dung thu tu thoi gian.
{consistency_step_text}
3. Voi TUNG tieu chi, xet tren toan bo round (khong chi 1 luot rieng le), chi ro luot noi \
nao the hien tot / chua tot.
4. Sau khi phan tich xong CA 5 tieu chi, viet "consistency_note": nhan xet TONG HOP ve tinh \
nhat quan cua learner xuyen suot round, dua tren nhung gi vua phan tich o buoc 2 va 3 — day \
la phan Chain-of-Thought bat buoc. KHONG can va KHONG nen tu dua ra 1 round_score rieng — \
diem tong (round_score) se duoc HE THONG TU DONG TINH tu 5 diem tieu chi ban vua cham o tren, \
khong can ban tinh hay chot.

[LUU Y CHONG THIEN VI]
- KHONG dung do dai luot noi lam tieu chi ngam.
- KHONG so sanh voi "bai mau chuan" co dinh — tranh bien la kich ban MO.
- Danh gia CA ROUND, khong chi luot noi cuoi cung.

[OUTPUT - CHI tra ve JSON hop le, khong them text nao khac ngoai JSON]
{{
  "criteria": [
    {{"name": "Logic", "score": <1-5>, "reasoning": "<giai thich, xet tren ca round, tieng Viet>"}},
    {{"name": "Evidence", "score": <1-5>, "reasoning": "<giai thich, tieng Viet>"}},
    {{"name": "Relevance", "score": <1-5>, "reasoning": "<giai thich, tieng Viet>"}},
    {{"name": "Structure", "score": <1-5>, "reasoning": "<giai thich, tieng Viet>"}},
    {{"name": "Persuasiveness", "score": <1-5>, "reasoning": "<giai thich, tieng Viet>"}}
  ],
  "consistency_note": "<BAT BUOC, nhan xet TONG HOP ve tinh nhat quan xuyen suot round, tieng \
Viet — KHONG phai giai thich cho 1 con so round_score rieng, vi diem tong duoc he thong tu tinh>",
  "strengths": ["<diem manh, tieng Viet>", "..."],
  "weaknesses": ["<diem yeu, chi ro luot noi nao, tieng Viet>", "..."],
  "suggestions": ["<goi y cho round/luot sau, tieng Viet>", "..."]
}}"""


def build_round_user_prompt(req: RoundEvaluationRequest) -> str:
    stage_label = STAGE_LABEL.get(req.stage.value, req.stage.value)
    side_label = SIDE_LABEL.get(req.side.value, req.side.value.upper())

    turns_text = []
    for i, turn in enumerate(req.turns, start=1):
        speaker_label = "LEARNER" if turn.speaker == TurnSpeaker.LEARNER else "DOI PHUONG"
        turns_text.append(f"Luot {i} - {speaker_label}: {turn.text}")

    parts = [
        f"[MOTION]\n{req.motion}",
        f"[PHIA CUA LEARNER] {side_label}",
        f"[GIAI DOAN / ROUND] {stage_label}",
        "[TOAN BO CAC LUOT NOI TRONG ROUND, THEO THU TU]\n" + "\n\n".join(turns_text),
    ]
    return "\n\n".join(parts)


def build_round_evaluation_prompt(req: RoundEvaluationRequest) -> tuple[str, str]:
    """Tra ve (system_prompt, user_prompt), san sang goi LLM.

    System prompt duoc dung dong theo ArgumentContext suy ra tu turns cua req
    (xem infer_round_context) — mo ta Relevance, cau intro, va buoc kiem tra
    tinh nhat quan deu thay doi giua SOLO/INTERACTIVE (xem _rubric_for_context,
    _ROUND_INTRO_BY_CONTEXT, _ROUND_CONSISTENCY_STEP_BY_CONTEXT), phan con lai
    cua prompt giu nguyen.
    """
    context = infer_round_context(req)
    return _build_round_system_prompt(context), build_round_user_prompt(req)
