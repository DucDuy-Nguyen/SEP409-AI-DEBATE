"""
Rubric + prompt builder cho AI Evaluator.

Co so thiet ke (xem docs/ADPP_Related_Work_LLM_as_Judge.docx de biet chi tiet):
- TEN 5 tieu chi (logic, evidence, relevance, structure, persuasiveness) lay tu de
  cuong capstone goc (FALL26_Debate Practice Platform_TamPM.docx), duoc dua ra nhu
  mot rubric vi du ("e.g., logic, evidence, relevance, structure, persuasiveness").
- Co so ly thuyet cho viec VI SAO chon 5 tieu chi nay: Wachsmuth et al. (2017),
  "Computational Argumentation Quality Assessment in Natural Language" (ACL 2017) —
  khung phan loai nen tang trong NLP ve chat luong lap luan, chia thanh Cogency (Logic),
  Effectiveness (Rhetoric), va Reasonableness (Dialectic). 5 tieu chi phang cua ADPP
  anh xa vao khung nay: Logic/Evidence -> Cogency, Structure/Persuasiveness ->
  Effectiveness, Relevance -> Reasonableness (bao gom ca "kha nang chong do phan
  bien" — lien quan truc tiep den giai doan rebuttal trong tranh bien).
- Yeu cau Chain-of-Thought TRUOC khi cham diem: RISE-Judge (Yu et al., 2025, EMNLP)
  cho thay model khong bi ep phan tich tung buoc se mac loi cham diem co ban, ke ca
  voi model manh, khi bo qua CoT.
- Khong dung "bai mau chuan" co dinh / khong thien vi do dai: DEBO (Lee et al., 2024)
  ghi nhan hien tuong sycophancy va xu huong nguoi dung tin tuong mu quang vao AI;
  tranh bien la kich ban mo (Themis, Hu et al., 2025), noi dap an tham khao co the
  gay hai nhieu hon loi.

TRONG SO: ca 5 tieu chi co trong so BANG NHAU (20% moi tieu chi). Khung Wachsmuth
chi cho TEN cac chieu danh gia, khong dua ra thu tu uu tien giua chung — nen chia
deu trong so la lua chon mac dinh de bao ve nhat khi chua co huong dan khac tu
giang vien. Neu Thay Tam dua ra cach chia trong so khac, cap nhat RUBRIC ben duoi
(trong so phai cong lai bang 1.0).

THANG DIEM 5 TIEU CHI CON: moi tieu chi cham 1-5 (5 bac, kieu WUDC) — dung de
hien thi feedback chi tiet cho learner (strengths/weaknesses/suggestions theo
tung khia canh), VA de tinh overall_score bang cong thuc (xem ngay ben duoi).

OVERALL_SCORE — DOI TU CONG THUC SANG DANH GIA HOLISTIC DOC LAP (2026-09):
Ban dau overall_score = (tong 5 tieu chi / 25) * 10 — tuc lay trung binh cong
5 tieu chi doc lap. Batch test voi du lieu nguoi cham that (IBM Project Debater
dataset, xem docs/AI_DEVELOPMENT_LOG.md muc 3.3/3.6) phat hien AI cham qua
khat khe va diem dong cuc bat thuong so voi phan phoi diem nguoi that. Gia
thuyet: de dat overall cao, cong thuc bat buoc CA 5 truc doc lap deu phai cao
CUNG LUC — xac suat nay thap hon nhieu so voi 1 danh gia tong the duy nhat
(hieu ung "nhan don do khat khe" / compounding conservatism). Huong xu ly luc
do: yeu cau AI tu dua ra 1 overall_score RIENG, thang 0-10, khong bi ep khop
cong thuc — xem lich su chi tiet trong docs/AI_DEVELOPMENT_LOG.md.

OVERALL_SCORE — DAO NGUOC LAI VE CONG THUC (2026-09, tiep theo quyet dinh tren):
Da lam thi nghiem so sanh truc tiep 2 cach tinh TREN CUNG 1 bo du lieu da cham
san (scripts/compare_overall_score_methods.py, 0 API call moi, tinh lai tu ket
qua batch Dagstuhl-15512 truoc do): Holistic cho r=0.585, Formula (tong 5 tieu
chi/25*10, tinh lai tu CHINH 5 diem tieu chi AI da cham, khong doi gi o buoc
cham chi tiet) cho r=0.601 — chenh lech nam trong bien do nhieu thong ke
(n=22), tuc HAI CACH TINH NGANG NHAU ve do khop voi nguoi cham that.

Trong khi do, Holistic da duoc chung minh KHONG ON DINH: case arg35720
(scripts/run_reasoning_consistency_check.py) cham 3 lan doc lap, Run 2 va
Run 3 co DUNG 5 diem tieu chi con giong het nhau (Logic=2, Evidence=1,
Relevance=4, Structure=2, Persuasiveness=2) nhung overall_score nhay tu 2.0
len 3.5 — vi AI "tu cam nhan" doc lap, khong bi rang buoc boi chinh 5 con so
no vua dua ra.

=> Vi 2 cach tinh NGANG NHAU ve do khop nguoi that, nhung Formula ON DINH +
MINH BACH + KIEM CHUNG DUOC hon nhieu (cung 5 diem tieu chi LUON cho ra CUNG
1 overall_score, khong phu thuoc "cam nhan" ngau nhien cua 1 lan goi LLM),
QUYET DINH QUAY LAI CONG THUC: overall_score = (tong 5 tieu chi / 25) * 10,
LUON LUON tinh nhu vay trong code (app/services/evaluator.py) — KHONG con
hoi AI tu cham 1 overall_score rieng nua, va neu LLM co lo tra them field
"overall_score" trong JSON, gia tri do bi BO QUA hoan toan, khong doc. Xem
toan bo chuoi suy luan (ca 2 lan doi huong) trong docs/AI_DEVELOPMENT_LOG.md.

OVERALL_REASONING (2026-09, cap nhat Y NGHIA sau khi dao nguoc ve cong thuc):
Truoc day field nay dung de giai thich TAI SAO AI chon 1 muc overall_score
doc lap. Gio overall_score da tro lai la GIA TRI TAT DINH tinh boi cong thuc
(khong con AI tu cham), nhung VAN GIU field "overall_reasoning" (khong xoa) —
doi y nghia thanh 1 NHAN XET TONG HOP ngan gon ve chat luong chung cua lap
luan, dua tren nhung gi vua phan tich o 5 tieu chi con. Giu lai field nay de
tiep tuc nguyen tac Chain-of-Thought (RISE-Judge, Yu et al. 2025) — luon co 1
buoc "tong ket bang loi" di kem con so, tranh de model "dien so" ma khong tu
duy. Van la truong BAT BUOC, khong duoc de trong; thieu van bi coi la loi
dinh dang de kich hoat retry, giong cach xu ly truoc day.

NGON NGU: toan bo he thong (motion, argument, feedback) dung tieng Viet. Ten field
JSON (name, score, reasoning...) van giu tieng Anh vi day la API contract ky thuat
— chi noi dung GIA TRI (motion, reasoning, strengths...) can bang tieng Viet.

ARGUMENT CONTEXT — SOLO vs INTERACTIVE (2026-09): mo ta tieu chi Relevance nhac
den "phan bien dung luan diem doi phuong", nhung dieu nay KHONG ap dung duoc khi
khong co doi phuong (vi du: bai Opening doc lap, hoac benchmark ngoai nhu IBM
Project Debater dataset dung de validate — xem docs/AI_DEVELOPMENT_LOG.md).
"Type" nay (ArgumentContext) duoc SUY RA TU DONG tu viec request CO hay KHONG CO
opponent_argument_text — KHONG suy tu ten field 'stage', vi trong debate that,
speaker o stage "opening" cua phe thu 2 (vi du Opposition 1st speaker) van co the
co noi dung cua phe truoc de phan hoi, nen stage khong dang tin cay bang du lieu
opponent_argument_text thuc te co duoc truyen vao hay khong. Logic chon rubric
theo context duoc gom mot cho duy nhat (_rubric_for_context), khong rai if/else —
de sau nay de mo rong them context/tieu chi khac (vi du rieng cho Rebuttal/Closing
khi co du lieu validate) chi can them entry vao cac dict override ben duoi.
"""
from enum import Enum

from app.schemas import ArgumentEvaluationRequest


class ArgumentContext(str, Enum):
    """
    SUY RA TU DONG tu ArgumentEvaluationRequest.opponent_argument_text (xem
    infer_argument_context ben duoi) — KHONG phai field nguoi dung tu truyen vao,
    nen khong pha API/schema hien co.
    """

    SOLO = "solo"  # KHONG co opponent_argument_text (Opening doc lap, benchmark ngoai...)
    INTERACTIVE = "interactive"  # CO opponent_argument_text (co doi thu de phan bien)


def infer_argument_context(req: ArgumentEvaluationRequest) -> ArgumentContext:
    """Suy ra ArgumentContext TU DU LIEU THUC TE (co/khong opponent_argument_text),
    KHONG tu req.stage — xem giai thich trong docstring dau file."""
    if req.opponent_argument_text:
        return ArgumentContext.INTERACTIVE
    return ArgumentContext.SOLO


RUBRIC: list[dict] = [
    {
        "name": "Logic",
        "weight": 0.20,
        "description": "Lap luan hop ly, khong mau thuan noi tai, cac buoc suy luan noi tiep nhau chat che.",
    },
    {
        "name": "Evidence",
        "weight": 0.20,
        "description": "Lap luan co bang chung / vi du cu the ho tro, khong chi la khang dinh suong.",
    },
    {
        "name": "Relevance",
        "weight": 0.20,
        "description": "Lien quan truc tiep den motion, va (neu co) phan bien dung vao luan diem cua doi phuong.",
    },
    {
        "name": "Structure",
        "weight": 0.20,
        "description": "Cau truc ro rang: claim - reasoning - example/impact, de theo doi.",
    },
    {
        "name": "Persuasiveness",
        "weight": 0.20,
        "description": "Kha nang thuyet phuc tong the, xet tren tong hoa cac tieu chi tren.",
    },
]

assert abs(sum(c["weight"] for c in RUBRIC) - 1.0) < 1e-6, "Trong so rubric phai cong lai bang 1.0"
assert len(RUBRIC) == 5


# Mo ta rieng cho tung ArgumentContext, theo tieu chi. RUBRIC o tren la ban goc/
# mac dinh (tuong duong INTERACTIVE) — dung nguyen cho Round-level (round_prompt.py)
# vi 1 round luon co the co doi thu trong turns (xem ghi chu trong round_prompt.py).
# CHI Relevance thay doi giua cac context hien tai; 4 tieu chi con lai giu nguyen.
#
# MO RONG SAU NAY: them context moi (vi du rieng cho Rebuttal/Closing khi co du
# lieu validate) hoac override them tieu chi khac ngoai Relevance chi can them
# entry vao dict ben duoi — KHONG can sua _rubric_for_context() hay rai them
# if/else o noi khac.
_CRITERION_OVERRIDES_BY_CONTEXT: dict[ArgumentContext, dict[str, str]] = {
    ArgumentContext.INTERACTIVE: {
        "Relevance": "Lien quan truc tiep den motion, va (neu co) phan bien dung vao luan diem cua doi phuong.",
    },
    ArgumentContext.SOLO: {
        # Bo hoan toan phan "phan bien doi phuong" — khong co doi phuong de phan
        # bien trong context nay, giu yeu cau nay se khien AI hieu sai/danh gia
        # khong cong bang (vi du batch voi IBM Project Debater dataset, khong co
        # opponent_argument_text).
        "Relevance": "Lien quan truc tiep den motion.",
    },
}


def _rubric_for_context(context: ArgumentContext) -> list[dict]:
    """
    Tra ve 1 BAN SAO cua RUBRIC voi mo ta cac tieu chi duoc ghi de theo context
    (tra cuu tu _CRITERION_OVERRIDES_BY_CONTEXT o tren). KHONG mutate RUBRIC goc.
    """
    overrides = _CRITERION_OVERRIDES_BY_CONTEXT.get(context, {})
    return [
        {**criterion, "description": overrides.get(criterion["name"], criterion["description"])}
        for criterion in RUBRIC
    ]


GRADING_TIERS = """\
1 - Lap luan co loi nghiem trong, lech hoan toan khoi tieu chi, khong nen dung trong thuc te.
2 - Co phan dap ung tieu chi nhung chat luong tong the chua du.
3 - Co diem manh va diem yeu, diem manh lan diem yeu trong pham vi tieu chi.
4 - Chat luong tot, dap ung tieu chi, chi co vai diem nho can cai thien.
5 - Xuat sac, dap ung nghiem ngat moi tieu chi.\
"""


def _rubric_as_text(rubric: list[dict] | None = None) -> str:
    """Mac dinh dung RUBRIC goc (tuong duong ArgumentContext.INTERACTIVE) — cho
    phep round_prompt.py tiep tuc goi _rubric_as_text() khong tham so nhu cu."""
    rubric = rubric if rubric is not None else RUBRIC
    lines = []
    for i, c in enumerate(rubric, start=1):
        lines.append(f"{i}. {c['name']} — {c['description']}")
    return "\n".join(lines)


def _build_system_prompt(context: ArgumentContext) -> str:
    """Dung dung rubric (mo ta Relevance) tuong ung voi ArgumentContext da suy ra
    tu request — xem infer_argument_context() va _rubric_for_context() o tren."""
    rubric_text = _rubric_as_text(_rubric_for_context(context))

    return f"""Ban la giam khao tranh bien cong tam, danh gia lap luan cua nguoi tranh bien \
trong mot phien tranh bien theo mo hinh Asian Parliamentary.

TOAN BO PHAN GIAI THICH, NHAN XET, GOI Y trong ket qua tra ve PHAI viet bang TIENG VIET. \
Chi rieng ten cac field JSON (name, score, reasoning, overall_score, overall_reasoning, \
strengths, weaknesses, suggestions) va ten 5 tieu chi (Logic, Evidence, Relevance, Structure, \
Persuasiveness) giu nguyen tieng Anh vi day la quy uoc ky thuat co dinh — khong dich ten \
field/ten tieu chi.

[TIEU CHI - trong so bang nhau, moi tieu chi chiem 20% diem tong]
{rubric_text}

[HE THONG CHAM DIEM 5 BAC - ap dung cho MOI tieu chi o tren]
{GRADING_TIERS}

[QUY TRINH BAT BUOC - PHAI lam theo dung thu tu, khong duoc bo qua buoc nao]
1. Doc ky lap luan, nhac lai cac tieu chi lien quan truoc khi cham.
2. Voi TUNG tieu chi trong 5 tieu chi, xac dinh phan nao lam tot / phan nao \
chua tot trong lap luan.
3. Chi RO vi tri loi cu the (cau nao, luan diem nao) va giai thich TAI SAO do la loi — \
khong duoc cham diem ma khong giai thich.
4. Sau khi phan tich xong CA 5 tieu chi, viet "overall_reasoning": 1-2 cau \
TONG HOP nhan xet CHUNG ve chat luong lap luan, dua tren nhung gi vua phan \
tich o 5 tieu chi tren — day la phan Chain-of-Thought bat buoc, giup nguoi \
doc nam nhanh buc tranh tong the. KHONG can va KHONG nen tu dua ra 1 con so \
diem tong the rieng — diem tong (overall_score) se duoc HE THONG TU DONG \
TINH tu 5 diem tieu chi ban vua cham o tren, khong can ban tinh hay chot.

[LUU Y CHONG THIEN VI - BAT BUOC tuan thu]
- KHONG dung do dai cau tra loi lam tieu chi ngam. Cau tra loi ngan van co the dat \
diem cao neu di thang vao trong tam va lap luan chat che.
- KHONG so sanh voi mot "bai mau chuan" co dinh — tranh bien la kich ban MO, co nhieu \
huong lap luan hop le khac nhau cho cung 1 motion.
- Neu nguoi tranh bien dua ra lap luan trai voi quan diem pho bien nhung logic van \
chat che, KHONG duoc tru diem chi vi "khac thuong".

[OUTPUT - CHI tra ve JSON hop le, khong them text nao khac ngoai JSON]
{{
  "criteria": [
    {{"name": "Logic", "score": <1-5>, "reasoning": "<giai thich cu the, viet bang tieng Viet>"}},
    {{"name": "Evidence", "score": <1-5>, "reasoning": "<giai thich cu the, viet bang tieng Viet>"}},
    {{"name": "Relevance", "score": <1-5>, "reasoning": "<giai thich cu the, viet bang tieng Viet>"}},
    {{"name": "Structure", "score": <1-5>, "reasoning": "<giai thich cu the, viet bang tieng Viet>"}},
    {{"name": "Persuasiveness", "score": <1-5>, "reasoning": "<giai thich cu the, viet bang tieng Viet>"}}
  ],
  "overall_reasoning": "<BAT BUOC, 1-2 cau tieng Viet tong hop nhan xet CHUNG ve \
chat luong lap luan dua tren 5 tieu chi tren — KHONG phai giai thich cho 1 con so \
overall rieng, vi diem tong duoc he thong tu tinh, khong can AI tu cham>",
  "strengths": ["<diem manh 1, tieng Viet>", "..."],
  "weaknesses": ["<diem yeu 1, chi ro vi tri loi, tieng Viet>", "..."],
  "suggestions": ["<goi y cu the de cai thien luot sau, tieng Viet>", "..."]
}}"""


def build_user_prompt(req: ArgumentEvaluationRequest) -> str:
    stage_label = {
        "opening": "Mo dau",
        "rebuttal": "Phan bien",
        "closing": "Ket luan",
    }.get(req.stage.value, req.stage.value)

    side_label = {
        "pro": "Ung ho (Pro)",
        "con": "Phan doi (Con)",
    }.get(req.side.value, req.side.value.upper())

    parts = [
        f"[MOTION]\n{req.motion}",
        f"[PHIA NGUOI TRANH BIEN DANG DUNG] {side_label}",
        f"[GIAI DOAN] {stage_label}",
    ]

    if req.opponent_argument_text:
        parts.append(f"[LAP LUAN GAN NHAT CUA DOI PHUONG]\n{req.opponent_argument_text}")

    parts.append(f"[LAP LUAN CAN CHAM]\n{req.argument_text}")

    return "\n\n".join(parts)


def build_evaluation_prompt(req: ArgumentEvaluationRequest) -> tuple[str, str]:
    """Tra ve (system_prompt, user_prompt), san sang goi LLM.

    System prompt duoc dung dong theo ArgumentContext suy ra tu req (xem
    infer_argument_context) — CHI mo ta Relevance thay doi giua SOLO/INTERACTIVE,
    phan con lai cua prompt giu nguyen.
    """
    context = infer_argument_context(req)
    return _build_system_prompt(context), build_user_prompt(req)
