# Spec RAG Evidence — Buoc 1: Ha tang + kho fact ViFactCheck + do baseline retrieval

Branch: `feature/rag-evidence` (tach tu `fix/evaluator-closing-round`, commit f6c188d)
Thu muc lam viec: `AiServices/ai-evaluator-service/`

## Muc tieu buoc nay

Dung ha tang RAG cho Evaluator va do xem **retrieval** co lay dung evidence khong, tren du lieu ViFactCheck da loc 3 chu de (giao duc, moi truong, cong nghe).

**KHONG lam trong buoc nay:** claim extraction, verify bang LLM, sua prompt cham diem, sua endpoint `/evaluate*`. Cac API hien tai phai chay y nguyen, toan bo test hien co phai pass.

## Nguyen tac chung

- Giu dung convention cua repo: comment tieng Viet khong dau, Pydantic settings doc tu `.env`.
- RAG la tinh nang **bat tat duoc**: them `rag_enabled: bool = False` vao `Settings`. Khi tat, service khong import torch/sentence-transformers, khong can DB.
- Dependency nang (torch, sentence-transformers) tach ra `requirements-rag.txt`, KHONG them vao `requirements.txt`.
- Dataset tai ve va cache model KHONG duoc commit: them `data/`, `.hf_cache/` (hoac tuong tu) vao `.gitignore` cua service.

## 1. Ha tang DB

Tao `AiServices/ai-evaluator-service/docker-compose.yml`:
- Image `pgvector/pgvector:pg16` (KHONG dung `postgres:16-alpine` vi khong co pgvector).
- Container name `adpp-ai-evaluation-postgres`, DB `ai_evaluation`, map port **5433** (5432 dang dung cho Postgres cua ai-opponent-service).
- Volume rieng + init script trong `docker/postgres-init/` de `CREATE EXTENSION IF NOT EXISTS vector;` va tao schema.

Schema (SQL trong init script):

```
knowledge_source
  id            uuid pk
  topic         text not null      -- 'education' | 'environment' | 'technology'
  source_type   text not null      -- 'dataset' | 'url' | 'document' | 'manual'
  title         text
  url           text
  dataset_ref   text               -- vd 'vifactcheck:<article_id>'
  created_at    timestamptz default now()

fact_card
  id              uuid pk
  source_id       uuid fk -> knowledge_source(id) on delete cascade
  topic           text not null
  content         text not null
  citation        text
  published_date  date
  status          text not null default 'approved'   -- 'pending' | 'approved'
  embedding       vector(1024)                        -- bge-m3 dense = 1024 chieu
  content_tsv     tsvector generated always as (to_tsvector('simple', content)) stored
  created_at      timestamptz default now()
```
Index: HNSW tren `embedding` (cosine), GIN tren `content_tsv`, btree tren `(topic, status)`.
Dung config `'simple'` cho tsvector vi Postgres khong co stemmer tieng Viet.

Them vao `Settings`: `rag_enabled`, `rag_database_url` (mac dinh tro toi localhost:5433), `rag_embedding_model = "BAAI/bge-m3"`, `rag_top_k = 5`.

## 2. Module `app/rag/`

```
app/rag/
  __init__.py
  schemas.py      # FactCard, RetrievedFact (fact_id, content, citation, score, vector_rank, keyword_rank)
  chunker.py      # tach van ban thanh cac doan ngan
  embedder.py     # wrap bge-m3, lazy load, batch encode, normalize
  store.py        # ket noi Postgres (psycopg 3 + pgvector), insert source/fact, vector_search, keyword_search
  retriever.py    # hybrid search = vector + keyword, gop bang RRF
```

Yeu cau tung file:
- **chunker**: tach theo cau (dau `.`, `!`, `?`, xuong dong; can than so thap phan kieu `3,5` va viet tat), gom thanh doan khoang 2-3 cau, co overlap 1 cau. Ham thuan, khong phu thuoc DB.
- **embedder**: dung `sentence-transformers` load `BAAI/bge-m3`, tu dung GPU neu co (`cuda`), khong thi CPU. Model chi load lan dau goi (lazy). `normalize_embeddings=True`.
- **store**: moi ham search nhan `topic` va chi lay `status='approved'`. `vector_search` dung toan tu cosine `<=>`. `keyword_search` dung `plainto_tsquery('simple', ...)` + `ts_rank`.
- **retriever**: `retrieve(query: str, topic: str, k: int, mode: "vector"|"keyword"|"hybrid")`. Hybrid lay top 20 moi ben roi gop bang Reciprocal Rank Fusion (k_rrf = 60), tra ve top k. Phan RRF viet thanh ham thuan rieng de unit test duoc.

## 3. Script du lieu — `scripts/rag/`

### 3.1 `explore_vifactcheck.py`
- Tai dataset HF `tranthaihoa/vifactcheck` bang thu vien `datasets` (cache vao `data/`).
- **In ra ten cac cot va 2 dong mau cua moi split** — KHONG hardcode ten cot truoc khi xem.
- In phan bo: so claim theo topic, theo label, theo split.
- Neu co dataset `tranthaihoa/vifactcheck_gold_evidence`, in cot cua no va cach noi voi dataset chinh (id chung?).
- Dung lai o day, in ket qua. Khong ghi gi vao DB.

### 3.2 `filter_vifactcheck.py`
Loc ra 3 chu de, ghi `data/vifactcheck_3topics.jsonl`, moi dong co: `claim_id, split, topic (education|environment|technology), claim, label, article_id, context, gold_evidence (neu co)`.
- **education**: lay theo gia tri cot topic tuong ung Giao duc.
- **technology**: lay topic Khoa hoc / Cong nghe (neu co) + loc keyword tren context (vd: cong nghe, AI, tri tue nhan tao, ChatGPT, chuyen doi so, dien thoai, internet, mang xa hoi, robot, du lieu, an ninh mang, xe dien...).
- **environment**: KHONG co topic rieng → loc keyword tren context toan bo dataset (vd: moi truong, o nhiem, rac thai, chat thai, bien doi khi hau, phat thai, khi nha kinh, nhua, rung, nang luong tai tao, ngap, han han, xa nguon...).
- Danh sach keyword dat thanh hang so o dau file de chinh duoc. Viet hoa/thuong khong phan biet.
- Mot article chi gan 1 topic (uu tien topic goc cua dataset, roi den so keyword trung nhieu nhat).
- In bao cao: so article va so claim moi topic, phan bo label moi topic.

### 3.3 `ingest_vifactcheck.py`
- Doc `data/vifactcheck_3topics.jsonl`. Moi article duy nhat → 1 `knowledge_source` (`source_type='dataset'`, `dataset_ref='vifactcheck:<article_id>'`).
- Chunk `context` bang `chunker`, embed bang `embedder` (batch), insert `fact_card` voi `status='approved'`.
- Chay lai nhieu lan khong bi trung (xoa source cu cung `dataset_ref` truoc khi insert, hoac bo qua neu da co).
- In tong so source, so fact card moi topic, thoi gian embed.

### 3.4 `eval_retrieval.py`
Danh gia retrieval tren claim cua split **test** (chi label Supported + Refuted, vi NEI khong co evidence vang):
- Voi moi claim: `retrieve(claim, topic, k)` voi k = 1, 3, 5, 10 va ca 3 mode vector / keyword / hybrid.
- 2 do do:
  - **article_hit@k**: trong top k co it nhat 1 fact card thuoc dung article cua claim.
  - **evidence_hit@k** (chi khi co gold evidence): trong top k co fact card chua gold evidence (so khop sau khi chuan hoa khoang trang; chap nhan neu fact card chua >= 80% token cua cau gold evidence).
- In bang ket qua theo topic va tong, ghi them `data/results/retrieval_<timestamp>.json`.
- KHONG goi LLM trong script nay (khong ton token Groq).

## 4. Test

Them `tests/test_rag_chunker.py` va `tests/test_rag_retriever.py`:
- chunker: tach cau dung voi so thap phan va viet tat, overlap dung.
- RRF: thu tu gop dung voi input gia, xu ly fact chi xuat hien o 1 ben.
- Cac test nay KHONG can DB va KHONG load model.

Toan bo test cu phai van pass.

## 5. Tai lieu

- README service: them muc "RAG Evidence (thu nghiem)" huong dan `docker compose up -d`, `pip install -r requirements-rag.txt`, thu tu chay 4 script.
- `docs/AI_DEVELOPMENT_LOG.md`: them muc moi ghi lai quyet dinh thiet ke cua buoc nay (pgvector, bge-m3, hybrid RRF, tach requirements, loc 3 chu de) — so lieu baseline de trong, se dien sau khi chay.

## Khi xong, tra ve tom tat gom

1. Danh sach file tao/sua.
2. Output cua `explore_vifactcheck.py` (ten cot, phan bo topic).
3. Output cua `filter_vifactcheck.py` (so article/claim moi chu de).
4. Bang ket qua `eval_retrieval.py` neu da chay duoc.
5. Ket qua chay `pytest`.
6. Moi cho phai tu quyet dinh khac voi spec, kem ly do.
