# Bo du lieu danh gia RAG

## `extract_set.jsonl` — BAN NHAP, can nguoi duyet lai

15 lap luan tranh bien tieng Viet do Claude soan de do buoc tach claim (`scripts/rag/eval_extract.py`).
**Chua duoc nguoi duyet.** Truoc khi dung so lieu nay de ra quyet dinh, can doc lai tung lap luan va `expected_claims`.

- 3 chu de: education, environment, technology, moi chu de 5 lap luan, dai 112-135 tu.
- `kind`: `opinion` (5 bai, chi quan diem, ky vong 0 claim), `mixed` (7 bai, 1-3 claim tron voi quan diem),
  `stt` (3 bai, dang ban ghi giong noi: so viet bang chu, khong dau cau, co tu dem "thi", "kieu nhu", "a").
- `expected_claims` da chuan hoa so (chu so) va viet thanh cau doc lap.
- Claim thuc chung lay tu cac bai ViFactCheck co trong kho (split train), de buoc 3 co the verify lai duoc.
  Vi vay day khong phai phep thu cho claim ngoai kho.

Ban goc de script doc nam o `data/eval/extract_set.jsonl` (khong commit); file nay la ban sao de commit.
Sua o day thi chep lai sang `data/eval/` truoc khi chay script.
