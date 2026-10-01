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
- [ ] AI Debater (dialogue generation cho Practice mode) — CHUA BAT DAU. Day
      la phan AI con lai lon nhat, can lam de hoan thien "AI vs learner".
- [ ] Ket noi AI service voi Backend/DB that (hien AI service dang doc lap,
      chua co session/participant/DB that phia sau).
- [ ] Rubric + trong so can thay Tam duyet chinh thuc (xem muc 2.1).

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
