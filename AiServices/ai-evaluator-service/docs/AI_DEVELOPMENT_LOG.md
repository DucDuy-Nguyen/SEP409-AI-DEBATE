# AI Development Log — ADPP AI Evaluator

> Tài liệu sống, cập nhật liên tục trong quá trình phát triển module AI.
> Ghi lại: kiến trúc hiện tại, quyết định thiết kế + lý do, vấn đề đã gặp,
> việc còn treo. Không phải tài liệu nộp cuối kỳ — là working log giữa
> Khoa và Claude khi cùng phát triển.

---

## 1. Kiến trúc hiện tại

### 1.1. Ba cấp độ chấm điểm

| Cấp độ | Endpoint | Input | Output | File chính |
|---|---|---|---|---|
| Argument | `POST /evaluate` | 1 lượt nói + lượt đối thủ gần nhất | Điểm 5 tiêu chí, thang 10 | `app/services/evaluator.py` |
| Round | `POST /evaluate/round` | Toàn bộ lượt nói qua lại trong 1 giai đoạn | Điểm round + đánh giá tính nhất quán | `app/services/round_evaluator.py` |
| Session | `POST /evaluate/session` | Danh sách Round đã chấm | Điểm tổng (tính toán học) + báo cáo tổng hợp (LLM) | `app/services/session_evaluator.py` |
| Coaching (Argument) | `POST /coaching/argument` | Bài gốc + kết quả `/evaluate` đã có | Phương pháp cải thiện tiêu chí yếu + hướng phát triển chính ý (xem 2.8) | `app/services/coaching.py` |
| Coaching (Round) | `POST /coaching/round` | Round gốc + kết quả `/evaluate/round` đã có | Như trên, xét trên toàn bộ lượt nói của learner trong round (xem 2.8) | `app/services/coaching.py` |

Session KHÔNG gọi LLM để tính điểm — `overall_score` và `stage_breakdown` được
tính trung bình cộng từ các `round_score` đã có sẵn (minh bạch, kiểm chứng được,
không tốn thêm API call). LLM chỉ được dùng để tổng hợp phần nhận xét định tính
(`progress_trend`, `overall_strengths/weaknesses/suggestions`).

### 1.2. Cấu trúc file

```
app/
  config.py               # doc .env, chon LLM provider
  schemas.py              # Pydantic models: Argument/Round/Session request+result
  prompts/
    evaluator_prompt.py   # rubric goc (RUBRIC, GRADING_TIERS) + prompt Argument-level
    round_prompt.py        # prompt Round-level, tai su dung RUBRIC tu evaluator_prompt
    session_prompt.py      # prompt tong hop Session-level (chi qualitative)
  services/
    json_utils.py         # extract_json + call_llm_with_retry, dung chung ca 3 cap
    llm_client.py          # abstraction OpenAI / Anthropic / Gemini / Groq
    evaluator.py            # Argument-level service
    round_evaluator.py      # Round-level service
    session_evaluator.py    # Session-level service
  routers/
    evaluate.py            # 3 endpoint: /evaluate, /evaluate/round, /evaluate/session
tests/
  test_evaluator.py        # 8 test, FakeLLMClient
  test_round_evaluator.py  # 5 test, FakeLLMClient
  test_session_evaluator.py # 5 test, FakeLLMClient
  test_api.py              # 4 test, FastAPI TestClient (validation only)
data/
  test_cases.json          # 15 argument-level test case (batch eval)
  session_test_cases.json  # 5 session, 14 round (batch eval multi-round)
scripts/
  run_batch_eval.py         # batch argument-level -> Excel
  run_session_batch_eval.py # batch round+session-level -> Excel
```

Tổng: 22 unit/API test (pytest, chạy offline bằng FakeLLMClient, không tốn API
that). Batch script goi API that, dung de kiem chung chat luong chua diem.

### 1.3. LLM Provider

Ho tro 4 provider qua 1 interface chung `LLMClient.generate(system, user) -> str`,
doi provider chi can sua `.env`, khong sua code nghiep vu:

- OpenAI (`gpt-4o-mini` mac dinh)
- Anthropic (`claude-haiku-4-5-20251001`)
- Gemini (`gemini-2.5-flash`, dung SDK moi `google-genai`)
- Groq (`openai/gpt-oss-120b`, tai dung SDK `openai` voi `base_url` rieng vi
  Groq tuong thich format OpenAI)

**Dang dung: Groq**, vi co free tier khong can the trong luc chua chot ngan
sach OpenAI/Anthropic voi thay/nhom.

---

## 2. Quyet dinh thiet ke + ly do

### 2.1. Rubric — 5 tieu chi, trong so deu nhau

Ten tieu chi (Logic, Evidence, Relevance, Structure, Persuasiveness) lay tu
de cuong goc (vi du minh hoa, khong bat buoc chinh xac). Co so ly thuyet:
Wachsmuth et al. (2017) "Computational Argumentation Quality Assessment in
Natural Language" (ACL) — 3 tang Cogency/Effectiveness/Reasonableness, 5 tieu
chi ADPP anh xa vao khung nay (xem docs/ADPP_Related_Work_LLM_as_Judge.docx
da lam truoc do).

Trong so: CHIA DEU 20% moi tieu chi — vi Wachsmuth khong de xuat uu tien tang
nao hon, chia deu la lua chon trung lap nhat khi chua co huong dan tu thay Tam.
**CAN THAY TAM DUYET RUBRIC NAY** truoc khi dung chinh thuc trong bao cao.

Da doi chieu voi WUDC Debating & Judging Manual (Ottawa): WUDC cham HOLISTIC
(1 diem tong duy nhat, khong tach tieu chi doc lap) — khac voi thiet ke ADPP
(tach 5 tieu chi co trong so). Quyet dinh: GIU thiet ke tach tieu chi, vi ADPP
la nen tang HOC de luyen tap (can feedback chi tiet tung ky nang), khong phai
cham giai thi dau thuc te (chi can xep hang thang-thua). Can neu ro ly do khac
biet nay trong SRS neu hoi dong hoi.

### 2.2. Thang diem — 0-10, cong thuc quy doi tu 1-5

`overall_score = (tong 5 tieu chi 1-5 diem / 25) * 10`

Ly do: hoc sinh/giao vien VN quen thang 10 hon thang 5. Moi tieu chi van cham
1-5 (5-tier, kieu WUDC) de LLM de "hieu" muc do (co grading tier ro rang tung
muc), roi quy doi ra thang 10 chi o buoc hien thi cuoi.

**CAP NHAT (2026-09):** overall_score da quay lai tinh bang cong thuc, xem
chi tiet chuoi suy luan day du o muc 3.8.

### 2.3. Output JSON, khong dung tag [[ ]]

Ban dau tham khao Themis dung tag `[[diem]]` trong text tu do. Doi sang JSON co
cau truc (dung `response_format: json_object` cho OpenAI/Groq) vi de parse chac
chan hon trong code that, giam rui ro regex sai dinh dang.

### 2.4. Ngon ngu — tieng Viet toan bo

Ban dau lam tieng Anh, sau doi sang tieng Viet toan bo he thong (motion,
argument, feedback). Rieng TEN FIELD JSON (`name`, `score`, `reasoning`...) va
TEN 5 TIEU CHI giu tieng Anh — vi la API contract ky thuat, doi se pha schema.

### 2.5. Khong fact-check tinh xac thuc cua dan chung (Huong A)

Da quyet dinh: AI Evaluator CHI cham "co dung dan chung dung cach, lien quan,
du manh de ho tro luan diem hay khong" — KHONG xac minh dan chung do co dung
that ngoai doi hay khong (vi LLM khong co cong cu tra cuu real-time, ep no
"xac nhan dung sai" de bay ra hallucination). Day la thong le giong giam khao
debate thi dau that (khong real-time fact-check tung con so). Huong B (co
fact-check qua web search) de o muc "Future Work", khong lam trong pham vi
capstone.

### 2.6. Session score tinh toan hoc, khong goi LLM cham lai

Xem muc 1.1. Ly do: minh bach, kiem chung duoc, khong ton chi phi API cham lai
du lieu da co, tranh LLM cho ra diem khac nhau moi lan hoi lai cung du lieu.

### 2.7. Competition (2 nguoi that) — AI Evaluator khong can biet co "tran dau"

Da thong nhat: goi API 2 lan doc lap (1 lan/nguoi, dao vai `speaker` learner/
opponent), Backend tu so sanh 2 ket qua de xac dinh thang-thua. AI Evaluator
KHONG can them logic pairwise-comparison rieng — giu nguyen tac 2 service
(AI Debater / AI Evaluator) doc lap, khong biet ve nhau.

### 2.8. Coaching — goi y SAU KHI cham (2026-10, cap Argument + Round)

Van de: ket qua cham chi co `suggestions` 1-2 cau chung chung. Learner biet
minh yeu o dau nhung chua biet LAM THE NAO de sua, va chua duoc goi y phat
trien chinh y cua minh. Them endpoint rieng `POST /coaching/argument`, tra ve:
(1) phuong phap cai thien cho cac tieu chi yeu (diagnosis + methods +
application), (2) huong phat trien chinh luan diem learner da neu (core_claim
+ directions + LOAI dan chung nen tim).

Quyet dinh + ly do:
- **Nhan lai ket qua /evaluate, KHONG cham lai** (giong /evaluate/session
  nhan lai ket qua Round): 1 lan goi LLM thay vi 2, va nhat quan voi diem
  learner da thay (neu cham lai, diem co the khac do dao dong da biet o 3.8).
- **Code chon tieu chi can goi y, khong de LLM chon**: tieu chi <= 3 diem, thap
  nhat truoc, hoa diem theo thu tu RUBRIC, toi da 3; bai da tot (moi tieu chi
  >= 4) thi lay 1 tieu chi thap nhat. `current_score` luon lay tu ket qua cham,
  bo qua so LLM tu dua — cung nguyen tac 3.8. LLM tra sai/thieu ten tieu chi
  -> coi la loi dinh dang -> retry.
- **KHONG viet lai bai thay learner**: giu nguyen tac "khong bai mau chuan"
  (DEBO/Themis) — tranh learner chep nguyen van.
- **KHONG dua so lieu/nguon cu the, chi mo ta LOAI dan chung**: khop 2.5 (khong
  fact-check) va lich su hallucination 3.4. Khi chay that lan dau, AI van neu
  ten thanh pho cu the lam vi du "da ap dung lenh cam xe may" (khang dinh co
  the sai) -> da siet prompt cam neu ten quoc gia/thanh pho/su kien nhu vi du
  "da xay ra"; chay lai khong con xuat hien (moi kiem 1 lan, chua phai bang
  chung chac chan vi LLM co tinh ngau nhien).
- **Tai su dung ArgumentContext (SOLO/INTERACTIVE)**: bai khong co doi phuong
  thi mo ta tieu chi khong nhac "phan bien doi phuong".

**Mo rong sang Round (2026-10):** them `POST /coaching/round`, dung chung
system prompt, cach chon tieu chi va kieu ket qua (`CoachingResult`) voi cap
Argument. Khac: xet tren tat ca luot noi cua learner; context SOLO/INTERACTIVE
suy tu `turns` (tai su dung infer_round_context); round INTERACTIVE them yeu
cau goi y cach phan hoi luot cua doi phuong; `request.stage` phai trung
`evaluation.stage` (chan ghep nham ket qua round khac).

**2 loi phat hien khi chay that cap Round (S01 rebuttal), da sua:**
- AI van bia so lieu khi lach bang nhan "vi du" ("vi du: ty le tang 30% tram
  cam o nguoi dung Facebook tren 2 gio/ngay"). Siet prompt: cam ca trong vi du
  minh hoa, de trong con so (X%) hoac mo ta dinh tinh, chi duoc nhac lai so
  CO SAN trong bai learner. Chay lai 2 lan + quet tu dong moi con so khong co
  trong bai goc: chi con so thu tu luot noi ("luot 3 cua doi phuong"), khong
  con so lieu bia.
- Groq JSON mode tu choi output JSON hong phia server -> `400
  json_validate_failed` -> lot ra loi 500 (khong thuoc loai loi
  call_llm_with_retry bat). Loi CO SAN o GroqClient, anh huong MOI endpoint,
  khong rieng coaching. Sua: GroqClient doi loi nay thanh EvaluationParseError
  de duoc retry nhu loi dinh dang thuong; loi 400 khac van giu nguyen.
  Test: tests/test_llm_client.py.

---

## 3. Van de da gap (co bang chung cu the)

### 3.1. Groq model bi khai tu giua chung (17/6/2026)

`llama-3.3-70b-versatile` bi Groq khai tu, phai doi sang `openai/gpt-oss-120b`.
Bai hoc: LUON kiem tra model con active bang:
`curl https://api.groq.com/openai/v1/models -H "Authorization: Bearer <key>"`
truoc khi debug sau vao code neu gap loi 404 model_not_found.

### 3.2. JSON parse fail thoang qua, retry tu xu ly duoc

Ghi nhan 1 lan loi `TypeError: argument after ** must be a mapping, not str`
khi chay batch that voi Groq — LLM tra ve 1 phan tu trong `criteria` la string
thay vi object dung schema. `call_llm_with_retry` trong `json_utils.py` da bat
dung `TypeError`, tu retry va thanh cong lan 2. KHONG can sua gi — day la bang
chung retry logic hoat dong dung trong dieu kien that.

### 3.3. Score compression / ceiling effect (batch dau tien, argument-level)

Chay 15 test case da dang (tu manh co bang chung den lac de), ghi nhan:
- Overall score toan bo 15 case dao dong 2.4 - 7.2, CHUA BAO GIO cham 8+ du co
  3 case duoc thiet ke "gan hoan hao".
- Tieu chi Persuasiveness: trung binh 2.27/5, CHUA BAO GIO vuot qua 3/5 trong
  toan bo 15 case.
- Tieu chi Evidence: trung binh 1.67/5, hau nhu luon thap ke ca khi co trich
  dan cu the (ten truong, nam, journal, co mau).

Ket luan tam thoi: co the la AI dang cham khat khe hop ly (giong giam khao
WUDC that hiem khi cho diem gan tuyet doi), HOAC la van de calibration prompt.
CHUA THE KET LUAN chac chan vi thieu doi chieu voi nguoi cham that (xem muc 4).

### 3.4. AI hallucination — doc sai / bia noi dung khi giai thich diem (2 lan ghi nhan)

**Lan 1 (TC12, argument-level, dot batch dau):** Argument goc co so lieu ro
rang ("chiem hon 70% phuong tien nhung phat thai gap 3 lan oto"), nhung AI
cham Evidence chi 2/5 voi ly do "khong dua so lieu cu the" — mau thuan truc
tiep voi chinh noi dung no vua doc.

**Lan 2 (S01 + S03 closing round, dot batch Round/Session):**
- S01: argument goc noi "giam 30 phut/ngay dung mang xa hoi -> giam 20% cam
  giac co don" (giam dung -> giam co don). AI DAO NGUOC thanh "giam 20% cam
  giac co don KHI DUNG mang xa hoi", roi ket luan day la "mau thuan logic",
  cham Logic chi 2/5.
- S03: motion la "cam xe may luu thong trong noi do", nhung AI cham Relevance
  chi 2/5 voi ly do lien quan den "bat buoc doi mu bao hiem" — cum tu NAY
  KHONG HE XUAT HIEN trong motion hay argument. AI tu BIA ra 1 chu de khong
  ton tai roi cham sai dua tren do.

**Pattern dang ngo (chua du bang chung de ket luan chac, moi n=2):** ca 2 case
lan 2 deu roi vao round CLOSING — la round CHI CO 1 LUOT NOI (khong co luot
doi phuong). Gia thuyet: rubric/prompt Round hien tai co the dang bat loi voi
round chi 1 luot, vi tieu chi Relevance yeu cau "correctly rebuts the
opponent's point" — round khong co doi phuong de phan bien co the khien AI
"thieu ngu canh", de bia hoac cham khat khe hon de bu dap.

**Chua sua prompt cho van de nay — dang o giai doan ghi nhan, can kiem tra
them S02/S04 closing truoc khi quyet dinh co sua rubric/prompt hay khong.**

**CAP NHAT (2026-09) — DA SUA, co bang chung xac nhan:**

Da ap dung lai co che ArgumentContext (SOLO/INTERACTIVE) — von da build cho
Argument-level — sang ca Round-level (xem app/prompts/round_prompt.py,
infer_round_context()). Round duoc suy la SOLO neu turns KHONG co lượt nao
TurnSpeaker.OPPONENT (vi du: round Closing chi 1 luot noi cua learner),
INTERACTIVE neu co it nhat 1 luot OPPONENT.

Phat hien quan trong trong qua trinh sua: khac Argument-level (noi "doi
phuong" CHI xuat hien trong mo ta tieu chi Relevance), prompt Round-level
con nhac "doi phuong"/"phan bien" o CA cau mo dau (intro) LAN buoc kiem tra
tinh nhat quan (QUY TRINH BAT BUOC buoc 2) — neu chi sua mo ta Relevance se
KHONG du de loai bo het yeu cau "phan ung voi doi phuong" khoi 1 round
SOLO. Da them 2 dict tra cuu theo context (_ROUND_INTRO_BY_CONTEXT,
_ROUND_CONSISTENCY_STEP_BY_CONTEXT, cung pattern voi
_CRITERION_OVERRIDES_BY_CONTEXT) de sua triet de ca 3 diem, khong chi 1.

**Bang chung xac nhan da het loi (chay lai scripts/run_session_batch_eval.py
tren chinh 2 case da phat hien loi truoc do, sau khi sua):**

- S03 (truoc: bia "bat buoc doi mu bao hiem" khong co that trong de) — SAU
  KHI SUA, Relevance reasoning: "Noi dung tap trung vao loi ich moi truong
  va suc khoe cong dong, lien quan truc tiep den de xuat cam xe may trong
  do thi" — dung chu de that, khong con bia them khai niem nao ngoai de bai.
- S01 (truoc: dao nguoc chieu nhan qua nghien cuu Pennsylvania) — SAU KHI
  SUA, Weaknesses ghi dung ban chat: "Lap luan chua chung minh day du moi
  quan he nhan qua" — phe binh dung (tuong quan chua chac nhan qua), khong
  con dao nguoc chieu du lieu.
- Ca S01 va S03 (SOLO, closing 1 luot) deu co consistency_note trung thuc:
  "chi co mot luot noi, nen khong co su khong nhat quan giua cac luot" —
  AI KHONG con co "dien" ra tuong tac khong ton tai, dung tinh than dong
  "KHONG duoc gia dinh hay bia them noi dung" da them vao prompt.
- Doi chung voi S06/S07 (INTERACTIVE, cung stage closing nhung CO doi thu,
  test case moi them rieng de doi chieu): consistency_note THUC SU danh
  gia tuong tac ("phan bien doi phuong mot cach hop ly" - S06; "khong co
  dau hieu dong y mu quang hay thay doi lap truong" - S07) — xac nhan
  context INTERACTIVE van hoat dong dung, khong bi anh huong boi thay doi
  cho SOLO.

**Ket luan:** ca 2 case hallucination da biet deu duoc sua triet de, co bang
chung so lieu that (khong chi dua vao 31 unit test pass). Van de nay coi
nhu DA XU LY XONG o cap Round-level.

### 3.5. .env / venv setup tren Windows (khong lien quan AI, nhung ton thoi gian debug)

- `python -m venv venv` co the treo/loi voi Python cai tu Microsoft Store (bug
  sandbox cua Store, khong phai loi code) — giai phap: bo qua venv, cai thang
  vao global bang `pip install -r requirements.txt`, hoac cai Python ban
  chinh thuc tu python.org neu can venv that.
- `pytest` khong nhan dien truc tiep tren PowerShell — dung `python -m pytest`
  thay vi goi `pytest` truc tiep.

### 3.6. Agreement rate voi du lieu nguoi cham THAT (IBM Project Debater dataset)

Chay 20 bai phat bieu "Human expert" tu bo IBM Project Debater Speech Quality
Dataset (huggingface.co/datasets/ibm-research/debate_speeches, 152 bai that,
15 annotator/bai) qua AI Evaluator that (Groq/gpt-oss-120b). Ket qua:

- Pearson r = 0.206, p = 0.383 (KHONG co y nghia thong ke voi n=20)
- MAE = 2.1 tren thang 0-10
- Diem nguoi tap trung 6.5-8.7, diem AI tap trung 4.4-7.2 — AI chấm THAP HON
  nguoi mot cach he thong

**Ket luan tam thoi:** day la BANG CHUNG THU 3 (sau 2 lan tu tao du lieu o muc
3.3) cung chi ve 1 huong: AI dang co xu huong cham khat khe hon con nguoi mot
cach he thong (score compression). Vi day la du lieu nguoi that, DOC LAP, khong
phai do nhom tu tao — do tin cay cua phat hien nay CAO HON nhieu so voi 2 lan
truoc.

**Gia thuyet ky thuat:** overall_score la trung binh CONG cua 5 tieu chi DOC
LAP, moi tieu chi co mo ta bac 5 rat khat khe ("dap ung nghiem ngat MOI tieu
chi"). De dat overall cao, CA 5 tieu chi deu phai cao cung luc -> hieu ung
"nhan don do khat khe" (compounding conservatism) — xac suat dat diem cao o
ca 5 truc doc lap thap hon nhieu so voi chi can cao o 1 truc tong the (kieu
WUDC holistic). CHUA KIEM CHUNG gia thuyet nay, can thu nghiem them.

**Han che cua ket qua nay:** n=20 la mau nho, p-value khong co y nghia CO THE
do thieu statistical power (mau qua nho) chu khong chac chan la khong co
tuong quan that. Can tang n (vi du 40-50 bai) truoc khi ket luan chac chan.

Xem chi tiet: ibm_agreement_results.xlsx (sheet "Agreement Results" +
"Agreement Metrics"), script scripts/run_ibm_agreement_eval.py.

### 3.7. Ghi chu ve cac chi so thong ke dung de danh gia AI (de doc lai khi can)

Ba chi so nay dung de so sanh diem AI cham vs diem nguoi cham that (xem muc 3.6):

**Pearson r** — do XU HUONG 2 day diem (AI va nguoi) co tang/giam CUNG NHAU
hay khong. KHONG do do chinh xac tuyet doi. Vi du: neu AI luon cham THAP HON
nguoi dung 3 diem moi bai mot cach co dinh (nguoi cham 7 -> AI cham 4, nguoi
cham 9 -> AI cham 6), r se = 1.0 (tuong quan hoan hao) dù AI khong he "dung".
Thang do: -1 (nguoc hoan toan) -> 0 (khong lien quan) -> +1 (cung chieu hoan hao).

**p-value** — do CON SO r DO CO DANG TIN KHONG, dua tren so luong mau (n).
Mau cang it, cang de ra r "gia" (ngau nhien trung hop). p nho (< 0.05) ->
dang tin. p lon -> chua du bang chung de ket luan gi ca (KHONG co nghia la
"khong lien quan", ma la "chua biet"). Cung 1 gia tri r, tang n len se lam
p nho di (dang tin hon).

**MAE (Mean Absolute Error)** — do TRUNG BINH moi lan AI cham LECH nguoi bao
nhieu diem (so tuyet doi, tren thang 0-10). Day la con so "de hieu" nhat,
noi truc tiep muc do sai lech thuc te.

**Vi sao can ca 3, khong chi 1 cai la du:** r cao khong dam bao AI dung (vi
du tren: r=1.0 nhung AI sai co dinh 3 diem). MAE cao ma r cung thap (dung
tinh huong dang gap: r=0.206, MAE=2.1) la dau hieu XAU NHAT — nghia la AI
vua khong theo dung xu huong, vua lech nhieu diem, KHONG PHAI loi he thong
de sua (kieu "cong bu 2 diem la xong") ma la loi khong nhat quan.

## 3.8. Hanh trinh overall_score: Formula -> Holistic -> quay lai Formula (ket luan cuoi cung)

Day la chuoi quyet dinh quan trong nhat ve cach tinh overall_score, trai
qua nhieu buoc thu nghiem co bang chung so lieu that o moi buoc — ghi lai
day du de tranh lap lai sai lam neu sau nay co ai (ke ca chinh minh) nghi
lai huong cu.

**Buoc 1 - Formula ban dau:**
overall_score = (tong 5 tieu chi / 25) * 10. Don gian, xac dinh
(deterministic).

**Buoc 2 - Phat hien "score compression" tren batch IBM dau tien (15 test
case tu tao):**
- Overall score toan bo 15 case dao dong 2.4-7.2, CHUA BAO GIO cham 8+ du
  co 3 case thiet ke "gan hoan hao".
- Tieu chi Persuasiveness trung binh 2.27/5, CHUA BAO GIO vuot qua 3/5.
- Gia thuyet dat ra: cong thuc bat buoc CA 5 truc doc lap deu cao CUNG LUC
  moi ra overall cao -> hieu ung "nhan don do khat khe" (compounding
  conservatism).

**Buoc 3 - Doi sang Holistic (2026-09), dua tren gia thuyet o Buoc 2:**
AI tu danh gia 1 diem tong the doc lap, KHONG tinh tu cong thuc. Them field
bat buoc "overall_reasoning" de giai thich (dung nguyen tac Chain-of-
Thought, tham khao RISE-Judge).

**Buoc 4 - Batch dau tien voi IBM sau khi doi Holistic (n=20): KET QUA XAU
HON, khong tot len:**
Pearson r = 0.206, p = 0.383 (khong co y nghia thong ke). Tiep tuc dieu tra
thay vi ket luan voi.

**Buoc 5 - Phat hien quan trong: Case 3263 (IBM) - AI va nguoi dang do 2
KHAI NIEM KHAC NHAU, khong phai loi cong thuc:**
Bai "We should end the use of economic sanctions" duoc nguoi cham 8.33/10
(cao nhat trong mau) nhung AI cham 4.33/10 (thap). Doc noi dung: bai la
hung bien cam xuc manh (starvation, mass loss of life) nhung HOAN TOAN
KHONG co dan chung cu the. AI cham dung theo rubric ADPP (phat vi thieu
Evidence). Nguoi IBM cham cao vi cau hoi annotator tra loi chi la "day co
phai bai mo dau HAY khong" (holistic thuan, thien ve rhetoric) - khac han
khai niem "5 tieu chi phan tich co Evidence rieng" cua ADPP.
=> Ket luan: IBM khong phai nguon validate phu hop cho rubric ADPP, KHONG
PHAI bang chung cong thuc gay khat khe.

**Buoc 6 - Tim nguon du lieu nguoi cham THAT khop dung khai niem hon:
Dagstuhl-15512-ArgQuality:**
Day chinh la du lieu THUC NGHIEM GOC cua Wachsmuth et al. (2017) - khung ly
thuyet ma rubric ADPP da dua vao tu dau. Co 15 chieu danh gia rieng biet
(Cogency, LocalSufficiency, GlobalRelevance, Arrangement, Effectiveness...)
anh xa duoc vao ca 5 tieu chi ADPP, khong chi 1 diem holistic nhu IBM.

**Buoc 7 - Batch Dagstuhl voi Holistic (n=22, sau khi da sua them
ArgumentContext SOLO/INTERACTIVE cho Relevance): KET QUA TOT:**
Ca 6 cap so sanh (Overall, Logic, Evidence, Relevance, Structure,
Persuasiveness) deu co p < 0.05 (co y nghia thong ke), r trong khoang
0.52-0.66 (tuong quan trung binh-kha). MAE 1.4-2.7/10.
=> Xac nhan Buoc 5: van de khong phai o cong thuc/holistic, ma o VIEC CHON
DUNG NGUON DU LIEU KHOP KHAI NIEM.

**Buoc 8 - Phat hien do khong on dinh cua Holistic (reasoning consistency
check, tieng Viet, n=5 argument x 3 lan/bai):**
Case arg35720: Run 2 va Run 3 co DUNG 5 diem tieu chi con GIONG HET NHAU
[Logic=2, Evidence=1, Relevance=4, Structure=2, Persuasiveness=2] nhung
overall_score nhay tu 2.0 len 3.5 (chenh 1.5/10). Chung minh: Holistic
KHONG chi la "cong thuc cu + nhieu nho" - no la 1 cach danh gia thuc su
khac, dao dong doc lap voi 5 tieu chi con da chot.

**Buoc 9 - Thi nghiem quyet dinh: Formula vs Holistic tren CUNG 1 du lieu
Dagstuhl (scripts/compare_overall_score_methods.py, tinh lai local, 0 API
call):**
| Cach tinh | r | p-value | MAE |
|---|---|---|---|
| Holistic (AI tu cham) | 0.585 | 0.0042 | 1.94 |
| Formula (cong trung binh) | 0.601 | 0.0031 | 1.99 |
Chenh lech r (0.016) nam trong bien do nhieu thong ke voi n=22 - HAI CACH
TINH NGANG NHAU ve do khop nguoi that. Nhung 12/22 bai (54.5%) lech nhau
>1.0 diem giua 2 cach tinh O TUNG BAI CU THE - Holistic khong on dinh hon,
chi la "khac" theo cach kho kiem chung.

**Buoc 10 - Doi chieu voi nghien cuu doc lap (Sternlicht et al., EMNLP
2025, "Debatable Intelligence: Benchmarking LLM Judges via Debate Speech
Evaluation", dung chinh bo du lieu IBM Project Debater):**
Bai bao xac nhan: LLM manh XEP HANG dung nhu nguoi (giong phat hien r on
dinh cua ADPP) nhung LUON CHO DIEM TUYET DOI THAP HON nguoi mot cach he
thong - goi la van de "calibration", DOC LAP voi cach tong hop diem (cong
thuc hay holistic). Cung xac nhan Chain-of-Thought cai thien agreement -
dung huong prompt ADPP da ap dung tu dau.

**KET LUAN CUOI CUNG (2026-09), da ap dung vao code:**
QUAY LAI Formula (cong trung binh 5 tieu chi / 25 * 10) cho overall_score,
LUON tinh bang cong thuc, khong dung gia tri AI tu de xuat rieng. Ly do:
- Formula va Holistic NGANG NHAU ve do khop voi nguoi that (Buoc 9).
- Formula ON DINH TUYET DOI (deterministic) - Holistic da chung minh dao
  dong o muc tung bai (Buoc 8) du 5 tieu chi con giong het nhau.
- Formula MINH BACH, DE GIAI TRINH voi hoi dong ("day la phep tinh toan
  hoc tu 5 diem da cham", khong phai "AI tu cam nhan").
- Van de "AI cham thap hon nguoi mot chut" (Buoc 4, 7, 10) la dac tinh
  chung cua LLM-as-judge da duoc ghi nhan trong nghien cuu doc lap (Buoc
  10), KHONG phai loi rieng cua cong thuc hay cua rubric ADPP - chap nhan
  duoc, khong can "sua" bang cach doi cong thuc.
Field overall_reasoning van giu lai (Chain-of-Thought), nhung gio la loi
giai thich cho 5 tieu chi da cham, khong phai ly do tu chon overall_score
(vi overall_score khong con do AI tu chon nua).

**MO RONG SANG ROUND-LEVEL (2026-09, cung ngay):**

Nguyen tac "LUON tinh bang cong thuc, bo qua gia tri AI tu tra ve" duoc ap
dung tiep sang Round-level (round_score trong app/services/round_evaluator.py),
sau khi phat hien 1 loi thuc te CUNG BAN CHAT: khi chay batch that
(scripts/run_session_batch_eval.py, session S02_declining), AI tra ve
round_score=14.0 (vuot thang 0-10 hop le) -> pydantic ValidationError ->
phai retry, ton them 1 lan goi API. Day chinh la bieu hien cu the, RO RANG
HON ve mat toan hoc, cua cung hien tuong da phat hien o Argument-level (case
arg35720): AI "tu cam nhan" 1 con so diem tong doc lap, khong rang buoc boi
chinh 5 diem tieu chi no vua cham.

Thay doi: round_score gio LUON duoc tinh = (tong 5 tieu chi / 25) * 10, bo
qua hoan toan bat ky gia tri "round_score" nao LLM co tra ve trong JSON.
Prompt (round_prompt.py) cung duoc sua dong bo: khong con yeu cau AI tu dua
ra round_score, chi con yeu cau viet "consistency_note" (nhan xet Chain-of-
Thought ve tinh nhat quan) — dung vai tro tuong duong "overall_reasoning" o
Argument-level.

Kiem chung: them test_round_score_ignores_ai_provided_value (tai hien
CHINH XAC tinh huong 14.0 da xay ra that, assert ket qua cuoi cung la gia
tri cong thuc, khong phai 14.0, va khong ton them lan retry nao). Chay lai
scripts/run_session_batch_eval.py tren toan bo 8 session (bao gom
S02_declining, session da gay loi truoc do) — KHONG CON xuat hien dong loi
ValidationError nao, ca 8/8 session chay het.

## 3.9. Thi nghiem: viet lai mo ta bac diem theo tung tieu chi (anchors) — KHONG DAT, da revert (2026-10)

**Gia thuyet:** diem tung tieu chi don thap (3.3) mot phan do 5 cau chung
`GRADING_TIERS`, dac biet bac 5 "dap ung nghiem ngat moi tieu chi" (nghi tu
3.6, chua tung kiem tra o cap tieu chi). Thay bang mo ta HANH VI cu the cho muc
1/3/5 cua TUNG tieu chi (behavioral anchors) se giam lech don thap.

**Cach do:** `scripts/run_dagstuhl_agreement_eval.py --n 30 --runs 2 --seed 42`,
chay baseline TRUOC khi sua prompt, roi chay lai CUNG mau sau khi sua. Them chi
so `mean_bias` (= TB AI - TB nguoi, co dau) vi Pearson r KHONG nhay voi lech
don (AI thap deu hon nguoi van co r cao) va `avg_ai_range` (dao dong giua cac
lan cham). Tieu chi quyet dinh chot TRUOC khi xem so: giu neu |mean_bias| co lai
o da so 6 cap, r Overall khong giam qua ~0.1, range khong tang ro.

| Cap | \|bias\| truoc -> sau | r truoc -> sau |
|---|---|---|
| Overall | 0.86 -> 1.13 (xau hon) | 0.605 -> 0.525 |
| Logic vs Cogency | 0.82 -> 0.69 (tot hon) | 0.370 -> 0.273 |
| Evidence vs LocalSufficiency | 1.88 -> 2.00 (xau hon) | 0.259 -> 0.194 |
| Relevance vs GlobalRelevance | 0.71 -> 1.67 (xau hon) | 0.610 -> 0.483 |
| Structure vs Arrangement | 1.95 -> 1.11 (tot hon) | 0.724 -> 0.513 |
| Persuasiveness vs Effectiveness | 0.51 -> 0.64 (xau hon) | 0.392 -> 0.232 |

**Ket qua: KHONG DAT** — bias chi co lai o 2/6 cap, va r GIAM o CA 6 cap (giam
nhieu nhat o Structure, 0.21). Theo tieu chi da chot -> da revert prompt ve
`GRADING_TIERS` cu. Giu lai phan chi so moi trong script (mean_bias,
avg_ai_range, `--output`) vi van huu ich cho cac thi nghiem sau.

**Nhan xet:**
- Lech KHONG mot chieu nhu gia dinh ban dau: o baseline, Overall (+0.86) va
  Relevance (+0.71) AI cham CAO hon nguoi; chi Evidence (-1.88) va Structure
  (-1.95) moi la don thap ro. Anchors noi long Structure duoc, nhung day
  Relevance va Overall lech them.
- Evidence sau khi sua bi cham ~1/5 gan nhu moi bai (range = 0): anchor muc 5
  doi "so lieu, nghien cuu, truong hop that" co the lai khat khe hon voi kieu
  argument ngan tren dien dan cua Dagstuhl.
- Luu y khi doc so Overall: diem tong theo cong thuc (tong/25*10) co san la 2.0,
  con diem tieu chi quy doi (score-1)/4*10 co san la 0 — 2 thang lech nhau, nen
  bias Overall khong so truc tiep voi bias tung tieu chi duoc.
- Han che: n=30, 1 lan thu, 1 bo anchors. Ket luan chi la "bo anchors NAY khong
  tot hon", chua phai "anchors noi chung vo ich". Neu thu lai: sua rieng tung
  tieu chi don thap (Evidence, Structure) thay vi doi ca 5 cung luc.

## 3.10. Dao dong diem giua 2 lan cham: tieng Viet vs tieng Anh (50 bai, 2026-10) — KET LUAN: CHUA CHAC CHAN, nghieng VI on hon o bai yeu

**Cau hoi:** tieng Viet co lam diem AI dao dong nhieu hon tieng Anh khong?

**Thiet ke:** 50 bai Dagstuhl, mau phan tang (20 bai diem nguoi > 5.0 chon ngau nhien
seed 42 + 30 bai <= 5.0), loai 3 issue khong gan duoc stance->side (school-uniform,
india, firefox-vs-ie). Moi bai cham 2 lan moi ngon ngu, CUNG bai, side theo stance
(25 PRO / 25 CON), prompt hien tai cua app/, temperature 0.2. Khac nhau duy nhat:
text (text_vi vs text goc) va motion (EN dich sat tu motion VI, KHONG phai slug goc
cua Dagstuhl). Ket qua: data/vi_variance_results.jsonl, data/en_variance_results.jsonl
(scripts/run_vi_variance_eval.py, scripts/analyze_vi_variance.py). Nguong chot truoc
(de xuat, chua co can cu nguon): diem tong SD gop <= 0.4 tren thang 0-10.

| Diem tong (0-10) | VI | EN |
|---|---|---|
| SD gop trong bai | 0.652 | 0.465 |
| Range TB giua 2 lan | 0.64 | 0.46 |
| ICC(2,1) [CI 95%] | 0.82 [0.70, 0.90] | 0.89 [0.82, 0.94] |
| Chenh TB (lan 2 - lan 1) | -0.13 [-0.38, +0.13] | +0.01 [-0.18, +0.19] |
| % bai lech >= 1.0 | 26% | 14% |
| Nguong SD <= 0.4 | KHONG DAT | KHONG DAT |

**Ket luan (chua chac chan):**
- VI - EN (SD gop diem tong) = +0.19, CI 95% [-0.01, +0.37] — sat 0, KHONG phai
  khac biet co y nghia thong ke chac chan. Ca hai ngon ngu deu khong dat nguong 0.4.
- Nghieng ve phia "VI on hon o bai yeu": SD gop diem tong o nhom bai nguoi cham <= 5.0
  la VI 0.73 vs EN 0.35; rieng 16 bai nguoi cham 0.0 la VI 0.89 vs EN 0.39. NHUNG nhom
  nguoi > 5.0 thi nguoc lai (VI 0.51, EN 0.59).
- Phan "bai yeu" la phan tich tham do, KHONG nam trong ke hoach chot truoc, n=16/30,
  nhieu phep so sanh -> chi coi la goi y, chua phai ket luan.
- Han che: moi ngon ngu chi 1 dot x 2 lan; chenh lech co the mot phan do cach dien
  dat motion EN (dich nguoc tu VI); mau lech ve diem thap; ban dich VI chua duoc nguoi
  Viet ra soat ngoai vai bai.
- Khong co troi he thong theo thu tu lan cham (moi CI cua "lan 2 - lan 1" deu chua 0).
- Diem TB 2 lan cua 2 ngon ngu cung mat bang (lech TB VI - EN ~ 0.00, r = 0.74 diem tong).

**Quan sat tu 6 lan cham lai 3 bai lech nhieu nhat** (response goc khong duoc luu nen
phai cham lai, data/_raw_dump_top.txt): ca 3 bai chi dai 1-2 cau; cac lan cham moi it lech
hon ban goc (hoi quy ve trung binh). Khi lech, ca 5 tieu chi nhich cung chieu (Logic,
Structure, Persuasiveness cung len/xuong) — dau hieu 1 phan doan chung ve "co lien quan khong"
keo theo cac tieu chi khac, khong phai nhieu doc lap tung tieu chi. Moi la quan sat tu 6 lan, chua kiem dinh.

**Ghi chu do luong:** cot `attempts` cua dot VI cu (data/vi_variance_results.jsonl) chua dem
request loi (log co 2 lan json_validate_failed khong co trong file); dot EN va cac dot sau da dem
dung (`failed_attempts`). Cong thuc diem tong da doi chieu 200/200 ban ghi: khop
`round(tong 5 tieu chi / 25 * 10, 2)`.

**Cap nhat sau thi nghiem temperature 0 (muc 3.12):** xu huong "VI on hon o bai yeu" KHONG on dinh —
o dot temperature 0, nhom nguoi <= 5.0 co SD gop 0.58 con nhom > 5.0 la 0.82 (nguoc voi dot 0.2: 0.73 / 0.51).
Nen coi phan "bai yeu" la nhieu cua mau nho, khong phai hieu ung da xac lap.

## 3.11. Diem tong khong vuot 7.2 (tran diem, ghi rieng) — CHUA XU LY

**Hien tuong (Dagstuhl, 50 bai x 2 lan x 2 ngon ngu, temperature 0.2):**
- Diem tong max quan sat: VI 7.2 (3/100 luot), EN 6.8 (1/100 luot); tong 5 tieu chi max 18/25 (VI),
  17/25 (EN). Khong co luot nao dat >= 7.6, du mau co 9 bai nguoi cham >= 8.33 (3 bai 10.0).
- Phan bo tung tieu chi (so luot o moi muc 1..5, VI | EN):
  Logic {22,36,35,6,1} | {16,45,37,1,1}; Evidence {63,35,2,0,0} | {60,40,0,0,0};
  Relevance {5,24,19,28,24} | {6,24,17,30,23}; Structure {26,33,37,4,0} | {20,40,39,1,0};
  Persuasiveness {25,46,29,0,0} | {21,52,27,0,0}.
  => Evidence va Persuasiveness KHONG BAO GIO vuot 3/5; Structure toi da 4; chi Relevance dung toan thang.
  Neu moi tieu chi chi dat toi da quan sat (5+3+5+4+3 = 20/25) thi tran ly thuyet cung chi 8.0.
- Bai nguoi cham 8.33-10 (n=9): AI TB 5.44 (VI) / 5.31 (EN) so voi nguoi 8.89; bai AI cao nhat TB 6.6 / 6.4.
  Bai nguoi 0-5 (n=27): AI TB 3.92 / 3.95 so voi nguoi 1.05. Tuc AI nen CA HAI DAU vao giua
  (cong thuc cung co san 2.0, khong cham duoc duoi 2.0 trong khi nguoi cham toi 0).

**Da biet / chua biet:**
- Da biet: tran nay giong het muc 3.3 (batch 15 case: diem 2.4-7.2, Persuasiveness khong qua 3/5,
  Evidence TB 1.67) va khong bien mat sau thi nghiem anchors (muc 3.9, Evidence bi day xuong ~1/5).
  Hien tuong ton tai o ca tieng Viet lan tieng Anh nen khong phai do dich.
- CHUA biet nguyen nhan: (a) rubric/bac 5 khat khe ("so lieu, nghien cuu, truong hop that" cho
  Evidence) voi doan binh luan dien dan ngan; (b) ban than du lieu Dagstuhl (doan ngan, khong the dat
  Evidence/Persuasiveness cao); (c) chuan chinh AI hop ly hon nguoi. Cac gia thuyet nay CHUA duoc kiem dinh.
- He qua: diem tong hien chi dung de xep hang tuong doi o khoang giua; KHONG tin duoc o hai dau thang
  (bai rat tot / rat te).

### 3.11.1. Gia thuyet vi sao Evidence va Persuasiveness khong vuot 3/5 + cach kiem tra re (CHUA CHAY, chua sua prompt)

Co so tu prompt hien tai (app/prompts/evaluator_prompt.py): Evidence = "Lap luan co bang chung / vi du cu the ho tro, khong chi la khang
dinh suong"; Persuasiveness = "Kha nang thuyet phuc tong the, xet tren tong hoa cac tieu chi tren"; bac 5 chung cho moi tieu chi =
"Xuat sac, dap ung nghiem ngat moi tieu chi"; quy trinh buoc 2-3 yeu cau chi ro phan chua tot / "vi tri loi cu the" cho tung tieu chi.
Quan sat da co: Relevance dung toan thang (52% luot dat 4-5); EN va temperature 0 cho CUNG tran -> ngon ngu va temperature da bi loai tru;
anchors muc 3.9 (nghieng ve "so lieu, nghien cuu") lam Evidence xuong ~1/5 chu khong nang tran.

| # | Gia thuyet | Du doan neu dung | Cach kiem tra | Chi phi API |
|---|---|---|---|---|
| H1 | Persuasiveness duoc DINH NGHIA la tong hop cac tieu chi khac nen tran cua no do Evidence/Logic quyet dinh, khong phai gioi han rieng | Persuasiveness <= TB bon tieu chi con lai o ~moi luot; hoi quy Pers ~ 4 tieu chi con lai R^2 cao; ly do cua Pers vien dan thieu bang chung/logic. (Da thay: 6/6 response dump deu mo dau "Do thieu bang chung...") | Offline: ty le Pers <= TB/max cac tieu chi khac, R^2, dem tu khoa trong 100 raw_model_output EN. Tuy chon P1: goi rieng CHI Persuasiveness voi dinh nghia doc lap ("nguoi nghe trung lap co dong y khong"), ~20 bai x 1 | Offline: 0. P1: ~22k token |
| H2 | Evidence thap la DUNG vi van ban: binh luan Dagstuhl ngan, it co vi du cu the | Bai co dau hieu bang chung (so lieu, %, URL, ten nguon) duoc AI Evidence cao hon ro; diem nguoi "sufficiency" cung thap o bai khong co | Offline: regex dau hieu bang chung tren 50 bai, so AI Evidence TB (300 luot) co/khong; so voi sufficiency cua nguoi (co the dung ca 316 bai chi voi diem nguoi). Neu bai co so lieu/URL van <= 2 -> AI khong ghi nhan bang chung (chuyen sang H3/H5) | 0 |
| H3 | Lech khai niem: "Evidence" cua AI = bang chung/vi du cu the; "local sufficiency" cua nguoi = tien de DU va PHU HOP cho ket luan | Nhieu bai nguoi cho sufficiency cao nhung AI Evidence = 1 va bai khong co vi du ngoai; tuong quan thap (da do r 0.26-0.54) | Offline: doc dinh nghia sufficiency/effectiveness trong guidelines.pdf (data/_dagstuhl_raw/.../guidelines.pdf); bang cheo sufficiency (nguoi) x Evidence (AI); doc tay ~10 bai lech nhat (nguoi cao, AI = 1) | 0 |
| H4 | Lech thang: nguoi cham 3 muc (low/medium/high -> 0/5/10), AI 5 muc; "high" cua nguoi co the ung voi AI 3-4 | Duong hieu chuan (diem nguoi TB theo muc AI) da cham ~8-10 o AI = 3 cho Evidence/Persuasiveness | Offline: bang/duong hieu chuan tu 300 luot x 50 bai + hoi quy don dieu (isotonic). Neu dung -> xu ly bang anh xa hieu chuan, KHONG can sua prompt | 0 |
| H5 | Quy trinh "boi loi" (buoc 2-3) + bac 5 "nghiem ngat" thien ve tru diem moi tieu chi | Moi tieu chi deu bi tru; nhung Relevance van 4-5 (52%) -> neu dung chi giai thich MOT PHAN | Offline: so strengths vs weaknesses trong 100 raw EN + 6 dump, tuong quan voi diem. Tuy chon P2 (script thu, KHONG sua app/): doi 1 cau buoc 3 thanh "neu ca dieu da lam tot va dieu kien de len muc cao hon", 12 bai x 1 | Offline: 0. P2: ~31k token |
| H6 | Hieu ung thu tu/neo: Persuasiveness sinh CUOI, sau 4 ly do toan "thieu bang chung" | Dao thu tu tieu chi trong template JSON lam Pers/Evidence doi ro | P3 (script thu): dao thu tu, 12 bai x 1. P1 (goi rieng) cung tra loi mot phan | ~31k token |
| H7 | Dac thu mo hinh (gpt-oss-120b cham khat/nen o thang 1-5) | Mo hinh khac, CUNG prompt va bai, cho Evidence/Pers 4-5 nhieu hon | P4: 12 bai x 1 tren provider khac (vd Gemini free tier neu co key) | token it, khong dung quota Groq |

Thu tu de xuat: (1) H1-H4 offline truoc (0 token, ~1 script, dung du lieu da co); (2) P1 neu H1 con mo; (3) P2-P4 chi khi offline chua phan biet duoc.
Ngan sach API xau nhat ~100k token. Ket qua se chi ra huong xu ly: anh xa hieu chuan (H4), dinh nghia lai/tach Persuasiveness (H1),
sua mo ta Evidence (H3), hay doi quy trinh/mo hinh (H5-H7).

**H8 (them sau): tran co the do dataset toan bai yeu** — du doan: bai chat luong cao that su se duoc AI cho Evidence/Persuasiveness >= 4.
Cach kiem tra: `scripts/probe_high_quality.py` (DA CHAY — ket qua o muc 3.11.4: khong ket luan theo quy tac; luc viet: 8-10 lap luan chat luong cao do nguoi dung cung cap, 1 lan/bai, dung dung
pipeline app/, khong sua app/; `--validate` va `--report` khong goi API; ghi data/high_quality_probe_results.jsonl). Chot truoc cach doc ket qua
(bao nhieu bai phai dat >= 4 de coi H8 duoc ung ho) TRUOC KHI chay. Tham chieu Dagstuhl: Evidence >= 4 va Persuasiveness >= 4 deu 0/300 luot.
Nhieu 1 lan cham ~0.4-0.5 diem tieu chi nen chi doc xu huong. Bien gay nhieu can ghi: do dai/the loai/nguon cua bai do nguoi dung chon.

### 3.11.2. Ket qua kiem tra offline H1-H4 + tran tham chieu tu dong thuan giua nguoi (2026-10, 0 token)

`scripts/analyze_ceiling_hypotheses.py` (bao cao: ceiling_hypotheses_report.txt; 300 luot cham AI x 50 bai; diem tung nguoi tu CSV goc).

**(a) Dong thuan giua nguoi va tran tuong quan AI-nguoi.** 3 nguoi cham chung ca 320 bai (thiet ke cheo day du), dung 48/50 bai ca 3 nguoi co diem hop le:
ICC(2,1) 0.41-0.63 (Structure thap nhat 0.41, overall cao nhat 0.63); do tin cay TB 3 nguoi ICC(3,3) 0.68-0.85 -> TRAN r(AI, TB nguoi) = sqrt(ICC(3,3)) = 0.83-0.92.
r(AI, nguoi) thuc te 0.38-0.59 (VI 4 lan / EN 2 lan) = khoang 43-65% cua tran (Evidence: r 0.43 / 0.49 vs tran 0.88; Persuasiveness 0.59 / 0.56 vs 0.91).
Ty le diem 'High' trong tung lan cham cua NGUOI (320 bai): Relevance 23.3%, Structure 15.4%, Logic 11.0%, overall 10.5%, Evidence 7.2%, Persuasiveness (effectiveness) 7.0%.
=> Thu tu chieu "kho dat High" cua nguoi giong thu tu tran cua AI (Relevance dung het thang, Evidence/Persuasiveness bi chan): mot phan tran la dac diem cua dataset/khai niem.

**H1 — Persuasiveness la ham cua cac tieu chi khac?** Phu hop, nhung chua tach duoc khoi hieu ung halo chung.
- Ly do cua Persuasiveness nhac "bang chung" o 100% / logic 94% / cau truc 41% / lien quan 8% (200 response tho); ly do Relevance (doi chung) nhac bang chung chi 1%.
- Persuasiveness - TB 4 tieu chi con lai = -0.26 (SD 0.39): thap hon 62% luot, bang 28%, cao hon 10%; 83% luot lech <= 0.5.
- R^2 khi hoi quy tung tieu chi tren 4 tieu chi con lai: Persuasiveness 0.76 (luot) / 0.88 (bai), nhung Logic 0.77 / 0.87, Structure 0.73 / 0.85, Relevance 0.70 / 0.84,
  Evidence 0.49 / 0.60 -> Persuasiveness khong "dac biet" hon Logic/Structure ve do phu thuoc.
- Bang cheo (so luot): Evidence = 1 -> Persuasiveness 1:68, 2:107, 3:8; Evidence = 2 -> 1:2, 2:33, 3:78; Persuasiveness > Evidence o 64% luot (cao hon thuong 1 bac), = o 34%.

**H2 — van ban khong co dau hieu bang chung?** KHONG DU DE KET LUAN: chi 6/50 bai co dau hieu (< 8): arg219204 (700, 90%), arg107456 (60, 80), 46238 (20, 13), arg54258 (study),
arg219206 (URL), 80854 (Scientists); tu khoa nguon da thu hep de han che duong tinh gia. Mo ta (khong ket luan): bai co dau hieu AI Evidence TB 2.04 (VI) / 1.92 (EN) vs 1.32 / 1.33 o 44 bai con lai;
chi 2/6 bai co it nhat 1 luot Evidence >= 3; diem nguoi (sufficiency) 6.94 vs 2.84. Bo sung phia nguoi tren 316 bai: 45 bai co dau hieu, sufficiency 3.59 vs 2.17.

**H3 — lech khai niem?** Co co so. Dinh nghia goc (annotation guidelines): local sufficiency = tien de "cung nhau cung cap du ho tro de hop ly rut ra ket luan ... khong tien gia dinh chap nhan duoc",
khong doi vi du cu the/so lieu; effectiveness = "thuyet phuc BAN ve lap truong tac gia ... co tinh den credibility va emotional force". Prompt AI doi "bang chung / vi du cu the" va Persuasiveness "tong hoa cac tieu chi tren".
Bang cheo 50 bai: nguoi > 6.67 (6 bai): AI Evidence <= 1.5 o 3 bai, 1.5-2.5 o 3 bai, khong bai nao > 2.5; nguoi <= 3.33 (29 bai): 23 bai AI <= 1.5.
Evidence ~ sufficiency: Pearson 0.45 / Spearman 0.49 vs tran 0.88. 8 bai nguoi cho sufficiency >= 5.0 nhung AI Evidence TB <= 1.5 da ghi vao data/_h3_audit.txt de doc tay (CHUA doc):
arg33261, 28415, 63512, arg33162, arg33280, arg35706, 73625, 46238.

**H4 — tran la lech thang, hieu chuan duoc?** KHONG ung ho du doan "o AI = 3 diem nguoi da ~8-10".
Diem nguoi TB (0-10) theo muc AI: Evidence 1 -> 2.4 (n=183), 2 -> 4.8 (n=113), 3 -> 5.8 (n=4, khong dang tin); Persuasiveness 1 -> 0.7, 2 -> 3.6, 3 -> 5.1 (n=70/142/88);
Logic 3 -> 5.7; Relevance 4 -> 6.7, 5 -> 6.3 (hai muc tren cung hau nhu khong phan biet). Cac muc 4-5 cua Evidence/Persuasiveness khong co du lieu nen anh xa don dieu khong khoi phuc duoc dau tren;
muc AI = 2 cua Evidence gom ca bai nguoi 0 lan 10 (34% bai co nguoi >= 6.67). Ket luan: van de la AI nen nhieu bai khac nhau vao cung muc, khong chi la lech tham chieu.

**Tong hop:** tran Evidence/Persuasiveness vua do ban chat chieu do (nguoi cung it cho High: 7%), vua do AI khong phan biet duoc bai tot (6 bai nguoi cho sufficiency cao: AI Evidence <= 2.5),
vua do dinh nghia khac nhau (H3) va ly do cua Persuasiveness duoc dung tu Evidence/Logic (H1, phu hop nhung chua tach khoi halo chung). Chua tach duoc cac nguyen nhan; H5-H8 chua chay.

**DANH SACH SUA THIET KE (quyet dinh cua nguoi dung, BAT KE ket qua kiem dinh):**
1. H1 — Persuasiveness hien duoc dinh nghia trong rubric la "tong hoa cac tieu chi tren" nen no khong cung cap thong tin doc lap va bi tran boi Evidence/Logic. Can dinh nghia lai
   (do rieng "nguoi nghe trung lap co dong y khong", gan voi effectiveness cua Dagstuhl) hoac bo/tach khoi cong thuc diem tong. Chua sua prompt/rubric.

### 3.11.3. H8 — quy tac doc ket qua (CHOT TRUOC KHI CHAY API, 2026-10)

**Vat lieu:** `data/high_quality_args.json`: 8 bai chat luong cao `hq01-hq08` (4 motion x 2 phe: cam chai nuoc nhua, to giac vo/chong giet nguoi,
hon nhan dong gioi, cha toi vs khong cha) + 2 bai doi chung `ctrl01` (cam chai nhua, pro), `ctrl02` (cha toi, con): dai ngang bai manh, lap y / giai thoai,
khong bang chung, ky vong diem thap. Van ban VIET RIENG cho probe (khong phai binh luan dien dan tu nhien), tieng Viet, 934-1085 ky tu
(Dagstuhl: TB 316, lon nhat 708) -> do dai la bien gay nhieu. `hq04` co diem yeu co y ve phap ly (bo qua ngoai le toi dac biet nghiem trong cua Dieu 19 BLHS).
**Cach cham:** `scripts/probe_high_quality.py`, 1 lan/bai, temperature 0.2, dung pipeline `app/` (khong sua prompt/rubric). Ket qua: `data/high_quality_probe_results.jsonl`.

**Quy tac (nguyen van yeu cau cua nguoi dung):**
- UNG HO H8 neu >= 6/8 bai hq co Evidence >= 4 VA >= 6/8 bai hq co Persuasiveness >= 4 VA ca 2 bai ctrl co Evidence <= 2.
- BAC BO neu <= 2/8 bai hq dat Evidence >= 4 HOAC <= 2/8 dat Persuasiveness >= 4.
- Con lai: KHONG KET LUAN, chay lai 8 bai hq them 1 lan.
- CO DO DAI neu mot bai ctrl co Evidence >= 3.
**Bao cao them (khong thuoc quy tac):** diem tong 8 bai hq; so bai co diem tong > 7.2; hq04 co bi tru Logic vi bo qua ngoai le Dieu 19 hay khong (doc ly do Logic trong response tho).
Ham `decide()` trong `scripts/probe_high_quality.py` cai dat dung quy tac (da test tren cac truong hop bien); `--report` in quy tac + ket qua, `--show hq04` in ly do tung tieu chi.

**Diem CHUA chot (khong tu y them quy tac):** (1) cach doc sau khi chay lai 8 bai hq (de xuat: ap quy tac cho tung lan rieng, chi ket luan neu ca hai lan cung huong; neu khac huong van "khong ket luan");
(2) neu ctrl Evidence >= 3 thi dieu kien "ung ho" khong the dat theo dinh nghia, ket qua la "khong ket luan" (hoac "bac bo" neu thoa dieu kien bac bo) kem co do dai;
(3) voi n = 8 va nhieu moi tieu chi ~0.4-0.5 diem moi lan cham, cac dem sat bien (5-6/8, 2-3/8) de dao chieu giua hai lan cham.

### 3.11.4. H8 — ket qua (2 lan cham, temperature 0.2, ~53k token) — THEO QUY TAC: KHONG KET LUAN

| | Lan 1 | Chay lai (8 hq) |
|---|---|---|
| hq Evidence >= 4 | 4/8 | 4/8 |
| hq Persuasiveness >= 4 | 5/8 | 7/8 |
| ctrl Evidence <= 2 (ca hai) | co (ctrl01 = 1, ctrl02 = 2) | (khong chay lai ctrl) |
| Ket qua theo quy tac | KHONG KET LUAN | KHONG KET LUAN |
| Diem tong hq (TB) / so bai > 7.2 | 7.90 / 6 trong 8 | 8.15 / 7 trong 8 |
| Co do dai (ctrl Evidence >= 3) | khong | - |

- Diem tong hq lan 1: hq01 8.4, hq02 8.4, hq03 6.8, hq04 7.6, hq05 8.8, hq06 8.4, hq07 6.8, hq08 8.0; chay lai: 8.4, 8.8, 8.4, 6.8, 8.4, 8.0, 7.6, 8.8.
  ctrl01 = 4.4, ctrl02 = 6.8. (Dagstuhl: diem tong lon nhat 7.2 tren 300 luot, khong luot nao co Evidence/Persuasiveness >= 4.)
- Evidence >= 4 o CA hai lan chi voi hq01, hq02, hq05 (cac bai dan nguon cu the: ten nghien cuu + nam + so lieu); 1 lan: hq06, hq08; 0 lan: hq03, hq04, hq07.
  => "tran <= 3" KHONG phai gioi han cung cua mo hinh/prompt: van ban co dan chung cu the duoc cham 4 (va Structure 5, diem tong toi 8.8). Nhung quy tac chua cho phep ket luan H8 vi Evidence chi dat 4/8
  (can >= 6/8) o ca hai lan; Persuasiveness dao dong nhieu giua hai lan (5/8 -> 7/8).
- Do dai khong phai nguyen nhan keo diem: ctrl dai 961 / 934 ky tu van chi Evidence 1 / 2. Nhung ctrl02 (giai thoai, lap y) van duoc diem tong 6.8 (Relevance 5, Structure 4), bang mot so hq ->
  diem tong bi Relevance/Structure keo len, khong tach duoc bai yeu-dai khoi bai tot o muc nay.
- hq04 (co y bo qua ngoai le toi dac biet nghiem trong cua Dieu 19): KHONG bi tru Logic vi diem nay. Ly do Logic o ca hai lan (3/3) la gia dinh nguoi pham toi se tu thu ma khong chung minh; reasoning khong nhac "ngoai le" va
  "dac biet nghiem trong" lan nao (0 lan o ca hai response). Mo hinh coi viec dan Dieu 19 la bang chung (Evidence 3 / 2, phe binh "thieu nguon cu the") ma khong kiem tra pham vi dieu luat — phu hop thiet ke khong fact-check (muc 2.5).
  (Chi 2 lan cham; hq03 trinh bay dung ngoai le nhung Logic 3 / 4 nen khong the tach hieu ung.)
- Han che: van ban viet rieng cho probe (khong tu nhien, nguoi viet khong doc lap voi nguoi chon), dai gap ~3 lan Dagstuhl, n = 8 + 2 ctrl, 1-2 lan cham, nhieu ~0.4-0.5 diem tieu chi moi lan.
  Quy tac chi quy dinh chay lai 1 lan; cach doc sau do chua chot (xem 3.11.3), khong tu y chay lan 3.

**KET LUAN (nguoi dung chot, khong chay lan 3): H8 KHONG KET LUAN theo quy tac.** Mo ta rut ra:
1. **Khong co tran cung.** Mo hinh/prompt hien tai cho Evidence 4, Persuasiveness 4, Structure 5 va diem tong toi 8.8 khi van ban co dan chung cu the.
2. **Tran 3/5 o Dagstuhl chu yeu la do dataset** (nhan dinh cua nguoi dung). Co so ung ho: (a) khong co tran cung (muc 1); (b) chi 6/50 bai Dagstuhl co dau hieu bang chung (muc 3.11.2, H2);
   (c) chinh nguoi cham cung hiem cho High o hai chieu nay (sufficiency 7.2%, effectiveness 7.0% tren 320 bai). KHONG duoc kiem dinh bang quy tac H8: day la dien giai, khong phai ket qua da kiem chung.
   Phan khac van ton tai ben canh dataset: AI nen nhieu bai khac nhau vao cung muc (H4), va dinh nghia Evidence/Persuasiveness khac khai niem cua nguoi cham (H3).
3. **Evidence >= 4 gan voi dan chung cu the (so lieu, ket qua nghien cuu cu the).** On dinh o hq01 (PET ~30%, vi nhua 93%/11 nhan), hq02 (Berman & Johnson 2015: ket qua cu the), hq05 (AAP 2013, Ha Lan 2001, hon 30 nuoc).
   Nhung khong du mot minh: hq07 (McLanahan & Sandefur 1994, mo ta dinh tinh) 3/3; hq08 (Jaffee 2003, Amato & Booth 1997) 3/4; hq06 (Civil Partnership Act 2004) 4/3.
4. **Diem tong khong tach ctrl02 khoi hq.** ctrl02 (giai thoai, lap y, Evidence 2) co diem tong 6.8 = hq03 lan 1 (6.8) = hq07 lan 1 (6.8) = hq04 lan chay lai (6.8), vi Relevance 5 va Structure 4 de dat cao.

**Track H DONG.** Cho nguoi dung chot 3 quyet dinh thiet ke (dinh nghia Evidence, dinh nghia Persuasiveness, trong so diem tong) roi moi sua `app/` (xem muc 4).

## 3.12. Thi nghiem temperature 0 tren 50 bai tieng Viet — KHONG GIAM dao dong (2026-10)

**Cau hoi:** dat `llm_temperature = 0` (chi trong script do, khong doi `.env`/`app/`) co lam hai lan
cham giong nhau hon khong? Cung 50 bai, side, text/motion VI, prompt; 2 lan/bai; nguong giu nguyen:
diem tong SD gop <= 0.4 (thang 0-10). Ket qua: data/vi_t0_variance_results.jsonl
(`scripts/run_vi_variance_eval.py --lang vi --temperature 0`, `scripts/analyze_vi_variance.py --lang temp`).

| Diem tong (0-10) | temperature 0.2 | temperature 0 |
|---|---|---|
| SD gop trong bai | 0.652 | 0.688 |
| ICC(2,1) [CI 95%] | 0.82 [0.70, 0.90] | 0.79 [0.64, 0.89] |
| Range TB giua 2 lan | 0.64 | 0.64 |
| % bai 2 lan cho dung cung diem tong | (khong do) | 34% |
| Nguong SD <= 0.4 | KHONG DAT | KHONG DAT |

- t0 - t0.2 (SD gop diem tong) = +0.04, CI 95% [-0.15, +0.26] -> khong thay khac biet; temperature 0 KHONG
  tao ra cham tat dinh: chi 34% bai cho 2 lan giong het (tieu chi rieng le 64-76%). Nguyen nhan chua xac dinh
  (co the nhieu phia Groq/ghep batch; chua kiem tra).
- MAE giua diem TB 2 lan cua t0 va t0.2 theo bai: 0.42 (diem tong), lech TB co dau +0.03 -> hai thiet lap cho
  cung mat bang; muc khac nhau nay cung cap voi nhieu giua 2 lan cua chinh moi thiet lap (range TB 0.64).
- MAE diem tong AI so voi diem nguoi: 2.54 (t0.2) vs 2.61 (t0); r = 0.58 vs 0.55. Luu y diem tong AI co san 2.0
  con nguoi toi 0 -> day chi la muc lech, khong phai do chinh xac.
- Evidence xau hon o t0 (ICC 0.58 vs 0.75, range TB 0.24 vs 0.14) nhung CI cua hieu SD gop chua 0.
- Han che: 1 dot x 2 lan moi thiet lap, n=50 mau phan tang. Ket luan chi la "dat temperature 0 khong giam
  dao dong o cau hinh nay", khong phai moi cach giam dao dong deu vo ich (chua thu cham nhieu lan lay trung binh).

### 3.12.1. Coi 4 lan cham VI (t0.2 x2, t0 x2) la 4 lan lap — SD gop cua TRUNG BINH k lan (offline, khong goi API)

`scripts/analyze_replicates.py` (bao cao: variance_report_replicates.txt). 50 bai, du 4 luot. Gia dinh: cac lan lap
doc lap, cung phuong sai (hai dot khong khac ro ve SD/mat bang: TB diem tong cac lan 4.59 / 4.46 / 4.62 / 4.50;
SD trong bai chi t0.2 = 0.652, chi t0 = 0.688, ca 4 lan sigma-hat = 0.635). SD gop cua TB k lan = SD trong bai cua
gia tri trung binh do. Bootstrap theo bai, 2000 lan, CI 95%. Nguong 0.4 goc duoc chot cho SD gop cua MOT lan cham;
ap vao TB k lan la so sanh theo yeu cau, KHONG phai nguong chot rieng cho trung binh.

| Diem tong (0-10) | SD gop | CI 95% | so voi 0.4 |
|---|---|---|---|
| k=1 (sigma-hat tu 4 lan) | 0.635 | [0.537, 0.738] | KHONG DAT |
| k=2, TB 3 cach ghep cap {12\|34},{13\|24},{14\|23} | 0.447 (tung cach: 0.393 / 0.500 / 0.446) | [0.377, 0.512] | KHONG DAT |
| k=2, doi chieu sigma-hat / sqrt2 | 0.449 | [0.380, 0.522] | KHONG DAT |
| k=3, TB 4 cach giu-1-lan (0.327 / 0.389 / 0.365 / 0.382) | 0.366 | [0.308, 0.424] | DAT (diem uoc luong) |
| k=3, doi chieu sigma-hat / sqrt3 | 0.366 | [0.310, 0.426] | DAT (diem uoc luong) |
| k=4, sigma-hat / 2 (chi ly thuyet) | 0.317 | [0.269, 0.369] | DAT (diem uoc luong) |

- k=2: diem uoc luong 0.447 nam tren 0.4 nhung CI [0.377, 0.512] chua 0.4 -> chua phan biet duoc chac chan. 1 trong 3
  cach ghep cap cho 0.393 (<= 0.4), 2 cach con lai 0.446-0.500. k=3: diem uoc luong 0.366 duoi 0.4 nhung can tren CI
  (0.424) van tren 0.4 -> "dat" chi theo diem uoc luong, chua chac chan theo CI.
- Cach tinh k=2 va k=3 doc lap nhau khop voi sigma-hat / sqrt(k) (0.447 vs 0.449; 0.366 vs 0.366), tuc gia dinh lap doc lap, cung
  phuong sai khong bi vi pham ro. Moi cach chia 4 lan thanh cap deu tron t0.2 va t0, nen neu co hieu ung temperature theo
  tung bai thi SD bi thoi nhe; coi la can tren.
- Tung tieu chi (thang 1-5, chi bao cao, khong dat nguong), SD gop k=1 | k=2 | k=3: Logic 0.41 | 0.29 | 0.24;
  Evidence 0.31 | 0.22 | 0.18; Relevance 0.54 | 0.38 | 0.31; Structure 0.44 | 0.31 | 0.25; Persuasiveness 0.41 | 0.29 | 0.24.
- Ham y: neu giu cau hinh hien tai, cham 3 lan roi lay trung binh (ton ~3x token) moi dua SD gop diem tong ve gan 0.37;
  2 lan chua du. Chua kiem tra bang 3 lan cham THAT rieng biet (day la ngoai suy tu 4 lan lap).

### 3.12.2. Ma tran tuong quan 5x5 giua cac tieu chi (Pearson, TB 4 lan, n=50)

| | Logic | Evidence | Relevance | Structure | Persuasiveness |
|---|---|---|---|---|---|
| Logic | 1.00 | 0.74 | 0.86 | 0.87 | 0.91 |
| Evidence | 0.74 | 1.00 | 0.63 | 0.69 | 0.74 |
| Relevance | 0.86 | 0.63 | 1.00 | 0.88 | 0.87 |
| Structure | 0.87 | 0.69 | 0.88 | 1.00 | 0.90 |
| Persuasiveness | 0.91 | 0.74 | 0.87 | 0.90 | 1.00 |

- Ngoai duong cheo: TB 0.81, nho nhat 0.63 (Evidence-Relevance), lon nhat 0.91 (Logic-Persuasiveness). Cac tieu chi cua AI
  di cung chieu rat manh -> 5 tieu chi KHONG doc lap, phu hop voi quan sat tu dump (muc 3.10) la khi lech thi ca 5 tieu chi nhich cung chieu.
- Tham chieu (ngoai yeu cau): cung 50 bai, 5 chieu Dagstuhl tuong ung cua NGUOI cham tuong quan voi nhau con CAO HON
  (TB 0.89, 0.80-0.96). Nen tuong quan cao giua cac tieu chi cua AI, rieng no, KHONG chung to AI "thien vi" hon nguoi.
- Evidence la tieu chi tuong quan thap nhat voi cac tieu chi con lai (0.63-0.74); no cung co SD giua bai nho nhat (0.46 so voi
  Logic 0.82, Relevance 1.11, Structure 0.78, Persuasiveness 0.65) vi gan nhu luon 1-2/5 -> r bi keo xuong boi thang bi co hep,
  chua tach duoc voi khac biet that su.

### 3.12.3. Cau truc nhieu giua cac tieu chi va mo phong cham thich ung (offline, khong goi API)

`scripts/analyze_noise_structure.py` (bao cao: variance_report_adaptive.txt), tren 4 lan lap VI (t0.2 x2, t0 x2), 50 bai.
Bootstrap theo bai 2000 lan, CI 95%.

**(1) Ma tran tuong quan 5x5 cua NHIEU** (nhieu = do lech moi lan cham so voi TB 4 lan cua chinh bai do, Pearson gop tren 50 x 4 do lech):

| | Logic | Evidence | Relevance | Structure | Persuasiveness |
|---|---|---|---|---|---|
| Logic | 1.00 | 0.52 | 0.43 | 0.48 | 0.52 |
| Evidence | 0.52 | 1.00 | 0.22 | 0.34 | 0.39 |
| Relevance | 0.43 | 0.22 | 1.00 | 0.45 | 0.54 |
| Structure | 0.48 | 0.34 | 0.45 | 1.00 | 0.57 |
| Persuasiveness | 0.52 | 0.39 | 0.54 | 0.57 | 1.00 |

- Trung binh ngoai duong cheo 0.45 [0.35, 0.55] (nho nhat 0.22 Evidence-Relevance, CI [0.02, 0.41]; lon nhat 0.57
  Structure-Persuasiveness). Moi CI cua 10 cap deu nam tren 0 -> nhieu giua cac tieu chi DONG BIEN co that, khong doc lap.
- Nhung yeu hon nhieu so voi tuong quan TIN HIEU giua cac bai (TB 0.81, 0.63-0.91): nhieu khong thuan tuy la mot "tang giam chung"
  (halo) ma chi mot phan chung. Gia tri rieng lon nhat cua ma tran nhieu = 2.80/5, tuc ~56% phuong sai nhieu nam tren 1 truc chung.
- He qua cho diem tong: SD trong bai quan sat 0.635; neu nhieu 5 tieu chi doc lap thi chi ~0.384 (0.4 x sqrt(tong phuong sai tung
  tieu chi)) -> nhieu tuong quan lam SD diem tong gap 1.65 lan, va cong thuc cong 5 tieu chi KHONG tu trieu tieu nhieu.
- Han che: diem la so nguyen 1-5, Evidence gan nhu hang so (cap co Evidence dua tren it do lech khac 0, CI rong).

**(2) Mo phong cham thich ung** (cham 2 lan, neu |lech diem tong| >= T them lan 3, lay TB cac lan da cham; 24 thu tu x 50 bai;
lan thu 4 la tham chieu doc lap voi viec chon; SD gop = sqrt(E[(uoc luong - tham chieu)^2] - sigma^2), sigma^2 = phuong sai trong bai
gop). Diem tong la boi cua 0.4 (1 diem tieu chi) nen T=0.4: he hai lan khac nhau la cham them; T=0.8: lech >= 2 diem tieu chi; T=1.2: >= 3.
Nguong 0.4 goc chot cho SD gop cua MOT lan cham; ap vao uoc luong thich ung la so sanh theo yeu cau.

| Phuong an | % them lan 3 | So lan TB/bai | SD gop [CI 95%] | so voi 0.4 | SD neu them lan 3 NGAU NHIEN cung ngan sach |
|---|---|---|---|---|---|
| co dinh 2 lan | - | 2.00 | 0.449 [0.380, 0.522] | KHONG DAT | - |
| thich ung T=0.4 | 68% | 2.68 | 0.398 [0.304, 0.520] | DAT (diem uoc luong) | 0.395 |
| thich ung T=0.8 | 40% | 2.40 | 0.422 [0.319, 0.543] | KHONG DAT | 0.418 |
| thich ung T=1.2 | 25% | 2.25 | 0.448 [0.352, 0.564] | KHONG DAT | 0.430 |
| co dinh 3 lan | - | 3.00 | 0.366 [0.310, 0.426] | DAT (diem uoc luong) | - |

- Cham thich ung KHONG cho loi ich so voi them lan 3 cho bai ngau nhien cung ngan sach: 0.398 vs 0.395, 0.422 vs 0.418, 0.448 vs 0.430
  (thich ung bang hoac nhinh hon, khong co CI cho hieu nay). SD gop hau nhu chi phu thuoc so lan cham TB, di theo duong gan
  tuyen tinh giua co dinh 2 lan (0.449) va 3 lan (0.366).
- Giai thich (suy luan, chua kiem dinh rieng): neu nhieu co cung do lon o moi bai, |lech giua 2 lan| khong cho biet gi ve sai so cua
  TRUNG BINH 2 lan nay; viec chon theo do lech chi giup khi mot so bai on hon han bai khac (phuong sai khac nhau theo bai) — o day khong thay ro.
- T=0.4 dat 0.398 voi 2.68 lan/bai nhung CI [0.304, 0.520] chua 0.4 rong -> "dat" chi theo diem uoc luong. Chi phi them ~34% so voi 2 lan co dinh.
- Do chech cua uoc luong thich ung so voi lan tham chieu rat nho (|chech TB| <= 0.003, moi CI chua 0) nen "SD gop" xap xi SD that.
  Cot chech cua phuong an co dinh bang 0 theo cau truc (doi xung 24 thu tu), khong mang thong tin.
- Gia dinh: cac lan lap hoan doi duoc (t0.2 va t0 coi nhu mot), nhieu khong phu thuoc nhieu vao bai; chua kiem chung bang cham that
  theo quy tac nay. Verifier lan dau FAIL (nhan "SD gop" co the gom binh phuong do chech; hang so 0.81 ghi cung) -> da do chech truc tiep va
  tinh 0.81 tu du lieu.

**Ket luan va quyet dinh cua muc 3.12 (track on dinh: TAM DUNG):**
- Nhieu giua cac tieu chi tuong quan ~0.45 (0.22-0.57): dong bien co that nhung chi mot phan chung (khong phai halo thuan tuy).
- Cham thich ung (them lan 3 khi lech) KHONG hon them lan 3 cho bai ngau nhien cung ngan sach -> BO huong nay.
- SD gop cua diem tong chi phu thuoc SO LAN CHAM: 1 / 2 / 3 lan -> 0.64 / 0.45 / 0.37 (nguong 0.4 chi dat tu khoang 3 lan,
  theo diem uoc luong). Temperature 0 khong thay doi dieu nay (muc 3.12).
- Quyet dinh: tach moi tieu chi thanh mot lan goi API rieng KHONG uu tien cho muc tieu on dinh (chua thu nghiem; ly do du kien:
  nhieu rieng tung tieu chi van co SD 0.4-0.5 o k=1 va chi phi tang ~5 lan so voi 1 lan goi).
- Chua lam: chua doi cau hinh san pham (van cham 1 lan, temperature 0.2); chua kiem chung bang cham that 3 lan.
- Track tiep theo: hieu chuan diem tran (Evidence/Persuasiveness khong vuot 3/5, muc 3.11) — CHUA sua prompt, xem 3.11.1.

## 3.13. Phan tich trong so diem tong (offline) — QUY TAC CHON CHOT TRUOC KHI CHAY (2026-10)

**Muc tieu:** so sanh 5 phuong an trong so DINH SAN A-E (khong hoi quy tu do) cho quyet dinh thiet ke "trong so diem tong" (muc 4). Chua sua `app/`.
**Moi phuong an bao cao:** (1) r voi diem nguoi (leave-one-out); (2) SD gop cua MOT lan cham tu 4 lan lap (t0.2 x2 + t0 x2, 50 bai; xem 3.12.1);
(3) khoang cach giua ctrl02 va trung binh 8 bai hq (diem tong tinh lai theo trong so cua phuong an, data/high_quality_probe_results*.jsonl).
**Quy tac chon (nguyen van yeu cau cua nguoi dung):** phuong an DON GIAN NHAT co r giam <= 0.03 so voi A VA tach ctrl02 khoi trung binh hq >= 1.0 diem; hoa thi chon SD thap nhat.
**Diem CHUA chot (cho nguoi dung):** (1) dinh nghia cu the A-E (A la phuong an goc de so r); (2) thu tu "don gian" giua cac phuong an; (3) "leave-one-out" co nghia gi khi trong so
da dinh san (khong co gi de fit): khong ap dung, hay bo lan luot tung tieu chi; (4) lay diem nguoi nao (gia dinh mac dinh: `overall_quality_score_10`, nhu cac phan tich truoc).

**DINH NGHIA DA CHOT (nguoi dung tra loi; thay cho cac diem "chua chot" o tren — nguoi dung cung tick "bo de xuat cua Claude" nhung chu da go la bo A-E KHAC, ap dung ban go):**
Diem tong = 2 x Sum(w_i x diem tieu chi i), thang 0-10 (A trung cong thuc hien tai). Thu tu trong so: Logic, Evidence, Relevance, Structure, Persuasiveness.
| | Logic | Evidence | Relevance | Structure | Persuasiveness | Ghi chu |
|---|---|---|---|---|---|---|
| A (goc) | 0.20 | 0.20 | 0.20 | 0.20 | 0.20 | cong thuc hien tai |
| B | 0.25 | 0.25 | 0.25 | 0.25 | 0 | bo Persuasiveness |
| C | 0.30 | 0.30 | 0.10 | 0.30 | 0 | B + giam Relevance |
| D | 0.25 | 0.25 | 0.25 | 0.25 | 0 | B + Relevance lam cong: neu Relevance cua LUOT CHAM do <= 2 thi diem tong luot do bi chan toi da 5.0 |
| E | 0.30 | 0.30 | 0.20 | 0.20 | 0 | B + Logic, Evidence nang hon |
**Thu tu don gian (co dinh, khong suy tu cong thuc): A < B < C = E < D.** Khi C va E cung dat dieu kien: ap quy tac hoa, chon SD gop mot lan cham thap hon.
**Cach tinh (chot truoc khi chay):** du lieu = 4 lan lap VI (t0.2 x2 + t0 x2) tren 50 bai (muc 3.12.1) cho r va SD; `high_quality_probe_results*.jsonl` cho khoang cach.
(1) r(leave-one-out): diem tong AI cua bai = TB cac luot cua bai (D: chan 5.0 ap dung tung luot TRUOC khi lay TB); r Pearson voi `overall_quality_score_10`; "leave-one-out" duoc hieu la
bo lan luot tung bai (50 lan, moi lan r tren 49 bai), bao TB (kem min/max) va dung gia tri TB nay cho quy tac; bao them r thuong tren 50 bai. (Nguoi dung chua tra loi cau hoi nay rieng; day la gia dinh.)
(2) SD gop mot lan cham = sqrt(TB phuong sai trong bai, ddof = 1, tren 4 luot) cua diem tong tung luot. (3) Khoang cach = TB diem tong 16 luot hq (8 bai x 2 lan) tru diem tong ctrl02 (1 luot); duong nghia la hq cao hon.
Dieu kien r: r_phuong_an >= r_A - 0.03. Diem nguoi: `overall_quality_score_10` (gia dinh mac dinh).

**KET QUA (`scripts/analyze_weights.py`, bao cao: weights_report.txt, 0 token; verifier PASS):**
| PA | r thuong (= r LOO TB) [LOO min, max] | d r vs A | SD gop 1 lan | TB hq / ctrl02 | khoang cach | dat r | dat >= 1.0 |
|---|---|---|---|---|---|---|---|
| A | 0.576 [0.552, 0.626] | 0 | 0.635 | 8.02 / 6.80 | 1.22 | dat | dat |
| B | 0.565 [0.540, 0.613] | -0.011 | 0.637 | 8.16 / 7.00 | 1.16 | dat | dat |
| C | 0.564 [0.539, 0.618] | -0.012 | 0.613 | 7.81 / 6.40 | 1.41 | dat | dat |
| D | 0.565 [0.540, 0.613] | -0.011 | 0.637 | 8.16 / 7.00 | 1.16 | dat | dat |
| E | 0.556 [0.532, 0.610] | -0.020 | 0.617 | 7.94 / 6.60 | 1.34 | dat | dat |
**KET QUA THEO QUY TAC: chon A** (nhom don gian nhat A da dat ca hai dieu kien; ca 5 phuong an deu dat nen quy tac khong loai ai ngoai thu tu don gian).
Nhan xet (khong thuoc quy tac):
- Quy tac suy bien: A dat khoang cach >= 1.0 (1.22, vi hq 8.02 vs ctrl02 6.80) nen A luon thang bat ke B-E; ket qua "A" khong noi gi ve gia tri cua B-E.
- Chenh lech giua phuong an nho hon do ngon cua mau. Bootstrap theo bai (2000 lan), hieu so voi A: d r B -0.011 [-0.025, +0.004], C -0.012 [-0.036, +0.011], D = B, E -0.020 [-0.039, -0.002] (chi E co CI loai tru 0, muc giam nho);
  d SD gop B +0.002 [-0.021, +0.025], C -0.022 [-0.060, +0.016], E -0.018 [-0.051, +0.013] (moi CI chua 0). r LOO TB trung r thuong den 3 chu so (trong so co dinh, khong co gi de fit).
- D trung B tung chi so: cong "Relevance <= 2 thi chan 5.0" khong kich hoat lan nao trong 200 luot (co 56 luot Relevance <= 2, nhung diem tong cua chung da <= 5.0), nen D khong khac B tren du lieu nay.
- Khoang cach dua tren ctrl02 CHI 1 LUOT (khong co CI); ctrl02 la bai doi chung do nguoi dung viet, khong phai phan phoi Dagstuhl.
- Bo Persuasiveness (B) giam r diem tong 0.011 (CI chua 0) va khong doi SD: viec bo Persuasiveness (muc 3.11.2, H1) khong lam mat tuong quan voi nguoi o muc do do duoc.

**Phu luc 3.9 — nguyen van bo mo ta bac Evidence da dung trong thi nghiem anchors (da `git restore`, khong con trong repo; khoi phuc tu transcript phien lam viec, dong Edit cua `app/prompts/evaluator_prompt.py`):**
```
Evidence — mo ta (khong doi): "Lap luan co bang chung / vi du cu the ho tro, khong chi la khang dinh suong."
  1: "khong co dan chung hay vi du nao, chi khang dinh"
  3: "co vi du hoac dan chung nhung chung chung, hoac chua gan chat voi luan diem"
  5: "dan chung cu the (so lieu, nghien cuu, truong hop that) ho tro truc tiep luan diem"
```
Cach dua vao prompt (`_rubric_as_text`): moi tieu chi in `"{i}. {name} — {description}"` roi 3 dong `"   - {level} diem: {anchor}"` cho muc 1, 3, 5; sau 5 tieu chi them dong:
`"Muc 2 va 4 nam giua 2 muc lien ke. Muc 5 KHONG doi hoi hoan hao tuyet doi — cham theo nhung gi bai THUC SU co, trong pham vi cua 1 luot noi."`
Thi nghiem do cung bo bo `GRADING_TIERS` ("5 - Xuat sac, dap ung nghiem ngat moi tieu chi") khoi system prompt.

## 3.14. Ba quyet dinh thiet ke da chot (nguoi dung, 2026-10) — CHUA SUA `app/`

1. **Evidence:** dung bo mo ta 5 bac MOI (ban nhap: **CHUA NHAN DUOC** — tin nhan chi co "[dan ban nhap]"); GIU NGUYEN `GRADING_TIERS`; chi thay mo ta bac cua Evidence (4 tieu chi con lai khong doi).
2. **Persuasiveness:** giu nguyen dinh nghia ("Kha nang thuyet phuc tong the, xet tren tong hoa cac tieu chi tren"); hien thi rieng nhu nhan dinh tong the; KHONG cong vao diem tong.
3. **Diem tong = phuong an B** (muc 3.13): Logic, Evidence, Relevance, Structure moi tieu chi 25%, Persuasiveness 0% (`diem tong = 2 x Sum(w x diem tieu chi)`, thang 0-10, san 2.0).

**Dot kiem tra sau khi sua `app/` (tren nhanh rieng):** 50 bai Dagstuhl (VI) + 10 bai probe (8 hq + 2 ctrl) x 3 lan; bao SD gop cua trung binh k = 1 / 2 / 3. **Quy tac doc ket qua (3 dieu kien): CHUA NHAN DUOC**
(tin nhan chi co "[dan 3 dieu kien]"); phai ghi vao day TRUOC khi chay. Ghi chu phuong phap: voi 3 lan lap, k = 1 la sigma-hat (SD trong bai), k = 2 uoc luong duoc doc lap bang cach "giu lai 1 lan"
(SD2 = sqrt(TB d^2 / 3), d = TB 2 lan - lan con lai), con k = 3 chi la ly thuyet sigma-hat / sqrt(3) (khong con lan nao de doi chieu).
**Ba diem da xac nhan (nguoi dung chon phuong an de xuat):** (a) Persuasiveness GIU trong `criteria` (van 5 muc, co score + reasoning, trong so 0) — FE/Backend va validator coaching khong phai doi;
(b) cong thuc moi ap dung cho Argument + Round (cung RUBRIC); Session van la trung binh `round_score`; (c) Persuasiveness bi LOAI khoi focus cua coaching.

**DA LAM tren nhanh `feature/rubric-b-weights` (chua commit; phan (2) + (3); phan (1) Evidence CHUA lam vi chua co ban nhap):**
`app/services/scoring.py` (moi, `compute_weighted_score`: `round(Sum(w x s) / 5 x 10, 2)`, nem `EvaluationParseError` neu ten tieu chi la/thieu/trung); RUBRIC weight 0.25 x4 + 0.0 (Persuasiveness);
`evaluator.py`/`round_evaluator.py` goi ham chung; 2 cau trong system prompt Argument va Round (header "trong so bang nhau 20%" -> "4 tieu chi x 25%; Persuasiveness khong tinh vao diem tong"; buoc 4 noi dung tuong ung);
mo ta field trong `schemas.py`; `coaching._select_focus_criteria` chi xet tieu chi co trong so > 0; README (rubric, cong thuc, vi du 4.4 -> 4.5 va 6.4 -> 6.5, so test 48 -> 61); test: `tests/test_scoring.py` (moi, 6 test)
+ them test o test_evaluator / test_round_evaluator / test_coaching. GRADING_TIERS va mo ta Evidence KHONG doi. Verifier: lan 1 FAIL (docstring con cong thuc cu) -> da sua.
**CON LAI truoc khi chay dot kiem tra:** (i) ban nhap 5 bac Evidence; (ii) 3 dieu kien doc ket qua (ghi vao day truoc khi chay); (iii) script chay 3 lan/bai + file ket qua rieng (khong tron voi du lieu cu).

### 3.14.1. Bo mo ta Evidence MOI + quy tac doc dot kiem tra (nguoi dung dan, CHOT TRUOC KHI CHAY, 2026-10)

**Mo ta Evidence moi** (thay mo ta/bac Evidence hien tai; GIU NGUYEN `GRADING_TIERS`; viet khong dau nhu prompt hien tai). Nguyen van:
```
Evidence: muc do luan diem duoc ho tro bang vi du, trai nghiem hoac du kien cu the.
Khong kiem tra du kien dung hay sai.
  1: chi khang dinh, khong co ly do hay vi du ho tro nao.
  2: co ly do ho tro nhung chung chung hoac hien nhien ("ai cung biet", "nhieu nguoi nhu vay"),
     hoac trai nghiem ca nhan khong gan ro voi luan diem.
  3: co it nhat mot vi du cu the, trai nghiem ca nhan, hoac lap luan nhan qua cu the
     gan truc tiep voi luan diem, du khong neu nguon.
  4: co it nhat mot du kien kiem chung duoc (so lieu, nghien cuu, dieu luat, su kien co ten)
     gan truc tiep voi luan diem.
  5: co nhieu du kien kiem chung duoc, moi du kien gan voi mot luan diem cu the,
     va co giai thich vi sao du kien do ho tro ket luan.
```
Dua vao prompt: dong tieu de `"{i}. Evidence — <2 cau dau, bo tien to "Evidence:" vi ten tieu chi da duoc in san>"` roi 5 dong `"   - {level} diem: <noi dung bac>"` (cung kieu hien thi cua thi nghiem anchors).

**QUY TAC DOC DOT KIEM TRA (nguyen van yeu cau cua nguoi dung):**
Cau hinh: 50 bai Dagstuhl + 10 bai probe (8 hq + 2 ctrl) x 3 lan, temperature giu nhu app, cong thuc B, ghi file ket qua rieng. Moc so sanh la so cua prompt cu duoi cong thuc B.
- **D1 — Evidence khong bi don cuc (50 bai Dagstuhl):** SD giua cac bai cua Evidence >= 0.60 (moc cu 0.46) VA r Evidence–sufficiency >= 0.43.
- **D2 — Probe:** hq01, hq02, hq05 moi bai co Evidence >= 4 o it nhat 2/3 luot; ctrl01 co Evidence <= 2 o ca 3 luot; trung binh diem tong 8 hq − trung binh ctrl02 >= 1.5 (moc cu 1.16).
- **D3 — Khong lam hong phan dang tot (50 bai Dagstuhl):** r diem tong voi overall_quality_score_10 >= 0.55 (moc cu 0.565) VA SD gop mot lan cham <= 0.70 (moc cu 0.637).
- **Quyet dinh:** dat ca D1, D2, D3 -> giu Evidence moi. Truot D1 hoac D2 -> bo Evidence moi, giu cong thuc B voi mo ta Evidence cu. Truot D3 (du dat D1, D2) -> dung, bao lai, chua quyet dinh.
- **Bao kem:** SD gop k = 1 va k = 2 (do duoc), k = 3 (ly thuyet sigma-hat / sqrt(3), ghi ro la ly thuyet); histogram Evidence 1-5 cu va moi; ket qua tung dieu kien kem con so.

**Cach hieu toi dung de tinh (chua duoc xac nhan rieng; neu sai thi sua truoc khi xem so):**
(a) Moc cu lay tu du lieu VI 4 lan lap (t0.2 x2 + t0 x2) tinh lai duoi cong thuc B: SD giua bai cua Evidence = SD (ddof = 1) cua TB cac luot moi bai (0.46, muc 3.12.2); r Evidence–sufficiency = Pearson cua Evidence TB cac luot voi `sufficiency_score_10` tren 48 bai du 3 nguoi cham (0.43, muc 3.11.2);
r diem tong / SD gop cua phuong an B (0.565 / 0.637, muc 3.13). Dot moi tinh dung cach do nhu vay (TB 3 luot thay cho 4; SD giua bai cua TB 3 luot co nhieu cao hon chut so voi TB 4 luot).
(b) D2 "trung binh diem tong 8 hq" = TB 24 luot (8 bai x 3), "trung binh ctrl02" = TB 3 luot cua ctrl02; diem tong la `overall_score` do app tra ve (cong thuc B). Moc cu 1.16 la gia tri cua B (muc 3.13, 16 luot hq / 1 luot ctrl02).
(c) "Truot D1 hoac D2" co uu tien hon "Truot D3": neu truot D1 hoac D2 thi bo Evidence moi bat ke D3.

**scoring_version (yeu cau them):** moi ban ghi diem co truong `scoring_version`: `v1_5x20` (cu: 5 tieu chi x 20%) va `v2_4x25` (moi: 4 tieu chi x 25%) de lich su va trung binh Session khong tron hai thang.
Ket qua Argument/Round trong API deu mang truong nay (thieu = `v1_5x20`, vi ban ghi cu); Session TU CHOI (422) neu cac round co scoring_version khac nhau [THAY DOI sau dot xac nhan, xem 3.15: Session GHIM theo round dau tien, khong tu choi]; ban ghi jsonl cua script cung luu truong nay.

### 3.14.2. Ket qua dot kiem tra v2 — THEO QUY TAC: BO Evidence moi (truot D1), giu cong thuc B + mo ta Evidence cu

Chay: 50 bai Dagstuhl VI x 3 (`scripts/run_vi_variance_eval.py --lang vi --n-runs 3 --tag v2` -> `data/vi_v2_variance_results.jsonl`, 150 luot) + 10 bai probe x 3
(`scripts/run_v2_probe.py` -> `data/high_quality_probe_v2_results.jsonl`, 30 luot), temperature 0.2, tong 556.583 token (459.167 Dagstuhl + 97.416 probe), 0 request loi; moi ban ghi `scoring_version = v2_4x25`;
doc bang `scripts/analyze_v2_check.py` (v2_check_report.txt). Diem tong luu khop cong thuc B tinh lai (sai so 0.0000).

| Dieu kien | Ket qua (moi) | Nguong | Moc cu (B) | |
|---|---|---|---|---|
| D1 SD giua bai cua Evidence (TB 3 luot) | 0.506 | >= 0.60 | 0.463 | TRUOT |
| D1 r Evidence–sufficiency (48 bai du 3 nguoi cham) | 0.415 (50 bai: 0.402) | >= 0.43 | 0.431 | TRUOT |
| D2 hq01 / hq02 / hq05 co Evidence >= 4 | 3/3, 3/3, 3/3 | >= 2/3 moi bai | — | DAT |
| D2 ctrl01 Evidence ca 3 luot | [1, 2, 2] | ca 3 <= 2 | — | DAT |
| D2 TB diem tong 8 hq − TB ctrl02 | 8.62 − 6.83 = 1.79 | >= 1.5 | 1.16 | DAT |
| D3 r diem tong voi overall_quality_score_10 | 0.645 | >= 0.55 | 0.565 | DAT |
| D3 SD gop mot lan cham | 0.624 | <= 0.70 | 0.637 | DAT |

**Quyet dinh theo quy tac:** truot D1 -> BO Evidence moi, giu cong thuc B voi mo ta Evidence cu. **Da ap dung** tren nhanh `feature/rubric-b-weights`: RUBRIC Evidence tra ve mo ta cu; cong thuc B, `scoring_version`, Session guard giu nguyen;
bo mo ta Evidence 5 bac van luu nguyen van o muc 3.14.1 va co che `levels` trong `_rubric_as_text` duoc giu (khong tieu chi nao dung) de thu lai sau.

**SD gop theo so lan cham (diem tong, thang 0-10):** k = 1: 0.624 (do duoc); k = 2: 0.442 (do duoc, "giu lai 1 lan"); k = 3: 0.361 (**LY THUYET** sigma-hat / sqrt(3), khong co lan nao de doi chieu).
Cu duoi B (4 luot): 0.637 / 0.447 (3 cach ghep cap) / 0.368 (ly thuyet).

**Histogram Evidence 1-5:** cu (200 luot) 1: 123 (62%), 2: 73 (36%), 3: 4 (2%), 4: 0, 5: 0 | moi (150 luot) 1: 105 (70%), 2: 37 (25%), 3: 8 (5%), 4: 0, 5: 0.

**Nhan xet (khong thuoc quy tac):**
- Mo ta moi LAM RO tren probe: hq01 Evidence 5/5/5 (diem tong 10.0 ca 3 luot), hq02 4/4/4, hq05 4/4/4, hq08 4/4/5; ctrl01 1/2/2, ctrl02 2/2/2 -> tran 3/5 khong con o probe (D2 dat voi khoang cach 1.79 so voi 1.16 cu).
- Nhung KHONG tach duoc bai that: tren Dagstuhl khong bai nao Evidence >= 4 (0/150), 70% luot la 1 (cu 62%). Bai co dau hieu bang chung (6 bai, muc 3.11.2): Evidence TB cu 2.04 -> moi 2.11; 44 bai con lai 1.32 -> 1.25; tuong quan theo bai giua Evidence cu va moi 0.56.
  Phu hop voi H2/H8 (muc 3.11): binh luan Dagstuhl hiem co du kien kiem chung duoc nen bac 4-5 khong the xuat hien; mo ta moi khong the lam phan bo Dagstuhl rong ra.
- D3 dat va tot hon moc cu (r 0.645 vs 0.565) nhung KHONG nen quy cho mo ta Evidence: cung luc doi cau chu trong so trong prompt, n = 50, chua co CI; r 0.645 chua duoc kiem dinh la khac r 0.565.
- Cau hinh cuoi cung dang trong `app/` (cong thuc B + mo ta Evidence cu + cau prompt moi ve trong so) CHUA duoc chay rieng 50 x 3; cac con so D3 o tren la cua cau hinh co mo ta Evidence moi. Neu can xac nhan, chay lai 150 luot (~390k token).

## 3.15. Dot XAC NHAN cau hinh cuoi bang API that — QUY TAC DOC CHOT TRUOC KHI CHAY REQUEST NAO (2026-10)

**Muc tieu:** do cau hinh cuoi cung trong `app/` (cong thuc B 4 x 25%, mo ta Evidence CU, cau trong so moi trong prompt, `GRADING_TIERS` giu nguyen, temperature nhu app = 0.2) tren 50 bai Dagstuhl VI va probe,
truoc khi commit. Cau hinh nay CHUA tung duoc do rieng (muc 3.14.2). Chua commit, chua push.

**Cau hinh dong bang (ghi truoc khi chay; `scripts/config_fingerprint.py`, sha256 noi dung, CRLF chuan hoa LF; moi ban ghi ket qua mang `config_hash` = hash tong hop):**
```
dfaf901edfcb5dc6783c55fbb4ddd78c3f09dbc44a7d60a0db8098b45d522de5  app/prompts/evaluator_prompt.py
26ad1dbeb7976e6af029bf5c96820084ad8defb2dd00cebf6f0c8588e6c0d65c  app/prompts/round_prompt.py
fb934a4b61d8cd5228e4d7ead48d956c1f2bcaa35ef006056c500290e2f33b1d  app/services/scoring.py
8eb86c0fc42e35ad9666b07ace7ec3a6d9c3fe94d8b6cb467cf9f4e3cdf02516  app/services/evaluator.py
9c6b7ba6d059a61d6c569500fa8e20adceb4cdd2551f46cd1e309ef1d7cf6b68  app/services/round_evaluator.py
8eaaf59ca8d40695a8e626bed7622e877afa1d92588ddb3a3de22349e582ef8d  COMBINED  (hash tong hop, so sanh bang `python scripts/config_fingerprint.py --check <hash>`)
```
Nhanh `feature/rubric-b-weights`, HEAD `dd2251b96b40cb9da58cc22885e04b13953ae8cb` (cac thay doi chua commit). `git diff --stat -- app/` (file da co trong git; `app/services/scoring.py` la file MOI chua duoc git theo doi nen khong hien trong stat):
`evaluator_prompt.py 41 | round_prompt.py 4 | schemas.py 47 | coaching.py 6 | evaluator.py 6 | round_evaluator.py 4 | session_evaluator.py 5` (7 files, 81 insertions, 32 deletions).
**Khong sua 5 file duoc bam hash (prompt/rubric/cong thuc) giua luc test va luc commit.** (Duoc phep sua sau khi dat: `schemas.py` — Session pin — khong nam trong danh sach bam hash, khong dung toi prompt/rubric/cong thuc.)

**Cau hinh dot chay:** 50 bai Dagstuhl VI (cung mau 50 bai) x 2 lan + 10 bai probe (8 hq + 2 ctrl) x 1 lan, ghi file RIENG `data/vi_confirm_variance_results.jsonl` va
`data/high_quality_probe_confirm_results.jsonl` (khong tron voi du lieu cu); moi ban ghi mang `scoring_version = v2_4x25`, `raw_model_output`, `config_hash`, `model`, `temperature` (script doc kiem tra model/temperature dong nhat va bang app). Uoc chung ~330k token (110 luot).
**Quota Groq:** header `x-ratelimit-*` chi cho gioi han theo phut/so request, khong cho gioi han token theo ngay; cac ngay truoc da dung ~530-560k token/ngay khong gap 429 nhung gioi han ngay that CHUA BIET
-> chay theo dot nho (`--max-new`), moi luot ghi ngay, tu bo qua muc da co; het quota ngay thi dung sach va bao con bao nhieu.

**QUY TAC DOC (nguyen van yeu cau cua nguoi dung):**
- r diem tong voi `overall_quality_score_10` >= 0.55 (50 bai, trung binh 2 lan)
- SD gop mot lan cham (diem tong) <= 0.70
- TB diem tong 8 hq − TB ctrl02 >= 1.0
- Dat ca ba -> nhanh san sang; sang buoc 4. Truot bat ky dieu kien nao -> DUNG, khong commit `app/`, bao lai so lieu. KHONG tu chay lai de tim lan "dat"; muon chay lai thi hoi nguoi dung truoc.
**Bao kem:** ba con so kem CI bootstrap neu tinh duoc (r va SD gop: bootstrap theo bai, 2000 lan; khoang cach: KHONG tinh duoc CI dung nghia vi ctrl02 chi 1 luot — chi co the bootstrap tren 8 hq voi ctrl02 co dinh, ghi ro),
histogram 5 tieu chi, so luot loi / 429, tong token, va moi luot bat thuong (parse loi, thieu tieu chi...). `scripts/analyze_confirm.py` cai dat quy tac nay.
**Cach hieu toi dung (chua duoc xac nhan rieng):** "vi pham toan ven" (scoring_version khac v2_4x25, config_hash lan nhau hoac khac hash tren, thieu raw_model_output, thieu/sai ten tieu chi, diem tong khong khop cong thuc B) lam VO HIEU dot chay
-> dung va bao lai; con retry/luot loi chi bao cao, KHONG tu chan buoc 4 (ket qua quyet dinh boi ba dieu kien).

**Buoc 4 (CHI khi dat ca ba):** (a) Session ghim `scoring_version` theo round dau tien thay vi tra 422 (khong dung prompt/rubric/cong thuc; them test); (b) ghi vao muc 4: mo lai so sanh hai bo Evidence khi co 30-50 bai that tu nguoi dung;
(c) commit thanh 2 commit: (1) scripts + docs phan tich; (2) `app/` cong thuc B + scoring_version + Session pin + test + README. Chua push.

### 3.15.1. Ket qua dot xac nhan — THEO QUY TAC: DAT CA BA (nhanh san sang)

Chay: 50 bai Dagstuhl VI x 2 (100 luot, `data/vi_confirm_variance_results.jsonl`) + 10 bai probe x 1 (`data/high_quality_probe_confirm_results.jsonl`), chia 4 dot nho (35 + 35 + 30 + 10 luot).
Khong gap 429 (khong luot nao loi hay thu lai); tong 294.143 token (request thanh cong). Moi ban ghi `scoring_version = v2_4x25`, `model = openai/gpt-oss-120b`, `temperature = 0.2`, cung `config_hash`
`8eaaf59c...2de` bang hash da ghi truoc khi chay; hash duoc kiem lai truoc moi dot va truoc khi commit. Khong vi pham toan ven (ten tieu chi, raw_model_output, diem tong khop cong thuc B).

| Dieu kien | Ket qua | CI 95% bootstrap theo bai | Nguong | |
|---|---|---|---|---|
| r diem tong (TB 2 lan) voi overall_quality_score_10, 50 bai | 0.598 | [0.404, 0.753] | >= 0.55 | DAT |
| SD gop mot lan cham (diem tong) | 0.579 | [0.469, 0.686] | <= 0.70 | DAT |
| TB diem tong 8 hq − TB ctrl02 | 8.19 − 7.00 = 1.19 | khong tinh duoc dung nghia (ctrl02 1 luot); bootstrap chi tren 8 hq: [0.62, 1.69] | >= 1.0 | DAT |

SD gop k = 1: 0.579 (do duoc); k = 2: 0.409 (**ly thuyet** sigma-hat / sqrt(2): chi 2 lan cham nen khong co lan de doi chieu).
Histogram (Dagstuhl, 100 luot, muc 1..5): Logic 12 / 50 / 31 / 6 / 1; Evidence 62 / 37 / 1 / 0 / 0; Relevance 3 / 19 / 18 / 38 / 22; Structure 15 / 38 / 37 / 10 / 0; Persuasiveness 14 / 49 / 36 / 1 / 0.
Probe (1 lan, diem tong): hq01 9.0, hq02 8.5, hq03 8.0, hq04 7.5, hq05 9.0, hq06 8.5, hq07 6.5, hq08 8.5 (TB 8.19); ctrl02 7.0.
Luu y khi doc: (i) CI cua r rong ([0.404, 0.753]) nen "dat >= 0.55" la theo diem uoc luong; (ii) khoang cach 1.19 chi hon nguong 0.19 va ctrl02 chi 1 luot (ctrl02 7.0 cao hon 6.83 o dot truoc),
khong co CI day du; (iii) mau 50 bai phan tang, lech diem thap (muc 3.11/3.12).

**Buoc 4 da lam (chi vi dat ca ba):** (a) Session GHIM `scoring_version` theo round dau tien thay vi tra 422 (xoa validator trong `SessionEvaluationRequest`; `session_evaluator.py` da dung `rounds[0].scoring_version`; test
`test_session_accepts_mixed_scoring_versions_and_pins_to_the_first_round`). He qua da biet: TB `round_score` van tron hai thang neu rounds khac phien ban; truong `scoring_version` cua Session chi cho biet phien ban cua round dau.
(b) Ghi muc 4: mo lai so sanh hai bo mo ta Evidence khi co 30-50 bai that tu nguoi dung. (c) Hai commit (xem lich su git cua nhanh `feature/rubric-b-weights`); chua push.


---

## 4. Viec con treo (chua lam / dang cho)

- [ ] **UU TIEN CAO: Dieu tra + xu ly score compression** (xem muc 3.6). 2
      huong thu nghiem: (a) tang n len 40-50 bai IBM de co ket luan thong ke
      chac chan hon, (b) thu nghiem doi cach tinh overall_score (vi du: bo
      bot yeu cau "MOI tieu chi" trong mo ta bac 5, hoac doi cong thuc tu
      trung binh cong sang cach khac) roi chay lai batch de so sanh r truoc/sau.

- [ ] **Agreement rate voi nguoi cham that (quan trong nhat, chua bat dau)**:
      can nguon diem nguoi cham — uu tien: (1) thay Tam cham mau 10-15 case
      (dang tin cay nhat, dung nghia "human judgment" NFR yeu cau), (2) ban
      be/thanh vien co kinh nghiem debate, (3) tu Khoa cham (chi de sanity
      check nhanh, KHONG dung lam so lieu chinh thuc vi Khoa la nguoi viet
      test case, de bias). Khi cham, PHAI an diem AI da cham truoc (blind
      review) de tranh anchoring bias.
- [ ] **Mo lai so sanh hai bo mo ta Evidence (cu vs 5 bac moi, muc 3.14.1-3.14.2) khi co 30-50 bai THAT tu nguoi dung** (cung kieu van ban se duoc cham trong san pham).
      Ly do: tren Dagstuhl mo ta moi khong tach duoc (khong bai nao Evidence >= 4) du probe cho thay no phan biet ro; Dagstuhl hiem co du kien kiem chung duoc nen khong dai dien cho bai that.
- [ ] AI Debater (dialogue generation cho Practice mode) — CHUA BAT DAU. Day
      la phan AI con lai lon nhat, can lam de hoan thien "AI vs learner".
- [ ] Ket noi AI service voi Backend/DB that (hien AI service dang doc lap,
      chua co session/participant/DB that phia sau).
- [ ] Rubric + trong so can thay Tam duyet chinh thuc (xem muc 2.1).
- [x] **Hieu chuan diem tran (Evidence/Persuasiveness <= 3/5) — TRACK H DONG (2026-10).** Da chay offline H1-H4 (muc 3.11.2) va H8 (muc 3.11.3-3.11.4:
      khong ket luan theo quy tac). KHONG lam them: doc tay data/_h3_audit.txt, probe API P1-P4, chay lan 3 cho H8 (mo lai neu can).
- [ ] **3 QUYET DINH THIET KE: DA AP DUNG tren nhanh `feature/rubric-b-weights` (chua commit/merge; muc 3.14-3.14.2). (2) Persuasiveness 0% va (3) cong thuc B GIU; (1) Evidence 5 bac moi da thu va BI BO theo quy tac (truot D1):**
      (1) dinh nghia Evidence; (2) dinh nghia Persuasiveness (da quyet dinh phai sua, bat ke ket qua: hien la "tong hoa cac tieu chi tren", dinh nghia lai
      hoac bo/tach khoi cong thuc diem tong — xem muc 3.11.2, danh sach sua thiet ke); (3) trong so diem tong (hien chia deu 20%, muc 2.1).

---

## 5. Nhat ky cap nhat

*(Moi lan co thay doi lon ve kien truc/quyet dinh, them 1 dong o day voi ngay
+ tom tat ngan — khong can chi tiet, chi tiet da co o cac muc tren.)*

- Khoi tao AI Evaluator, thiet ke rubric 5 tieu chi, thang 1-5.
- Doi rubric sang trong so deu 20%, thang tong quy doi ve 0-10.
- Doi prompt sang tieng Viet toan bo.
- Them ho tro Gemini, sau do Groq (theo thu tu uu tien tim provider free).
- Xay dung them Round-level va Session-level, tach `json_utils.py` dung chung.
- Batch test 15 case argument-level -> phat hien score compression + 1
  hallucination (TC12).
- Batch test 5 session / 14 round -> phat hien 1 hallucination nua (S01, S03
  closing) + gia thuyet "round 1 luot bi bat loi".
- 2026-10: Them endpoint Coaching cap Argument (`POST /coaching/argument`) —
  goi y sau khi cham, khong cham lai, khong viet lai bai (xem 2.8).
- 2026-10: Them `POST /coaching/round`; sua GroqClient retry khi Groq tra
  `400 json_validate_failed` (truoc day thanh loi 500) — xem 2.8.
- 2026-10: Thi nghiem anchors theo tung tieu chi (Dagstuhl n=30, do truoc/sau)
  -> KHONG DAT, da revert prompt; giu chi so mean_bias/avg_ai_range trong
  script do — xem 3.9.
- 2026-10: Do dao dong diem VI vs EN (50 bai x 2 lan x 2 ngon ngu) -> ket luan chua
  chac chan, nghieng VI on hon o bai yeu; ca hai khong dat nguong SD <= 0.4 — xem 3.10.
  Ghi rieng van de diem tong khong vuot 7.2 (tran diem) — xem 3.11.
- 2026-10: Thu temperature 0 tren 50 bai VI -> SD gop 0.688 vs 0.652 (0.2), khong giam dao dong,
  van khong dat nguong 0.4 — xem 3.12.
