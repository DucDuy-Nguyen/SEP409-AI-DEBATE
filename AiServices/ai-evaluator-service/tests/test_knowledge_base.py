from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import knowledge_base as kb_router


class _FakeStore:
    def __init__(self):
        self.sources: dict[str, dict] = {}
        self.facts: dict[str, dict] = {}
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def commit(self):
        self.committed = True

    def insert_source(self, topic: str, source_type: str, title=None, url=None, dataset_ref=None):
        sid = uuid4()
        self.sources[str(sid)] = {
            "id": str(sid),
            "topic": topic,
            "source_type": source_type,
            "title": title,
            "url": url,
            "dataset_ref": dataset_ref,
        }
        return sid

    def insert_facts(self, source_id, cards):
        for card in cards:
            fid = str(uuid4())
            self.facts[fid] = {
                "id": fid,
                "source_id": str(source_id),
                "topic": card.topic,
                "content": card.content,
                "citation": card.citation,
                "published_date": card.published_date.isoformat() if card.published_date else None,
                "status": card.status,
                "has_embedding": card.embedding is not None,
            }

    def list_sources(self, topic=None, limit=20, offset=0):
        items = [s for s in self.sources.values() if topic is None or s["topic"] == topic]
        return items[offset : offset + limit], len(items)

    def delete_source(self, source_id):
        key = str(source_id)
        if key not in self.sources:
            return False
        del self.sources[key]
        self.facts = {k: v for k, v in self.facts.items() if v["source_id"] != key}
        return True

    def list_facts(self, topic=None, status=None, source_id=None, query=None, limit=20, offset=0):
        items = list(self.facts.values())
        if topic:
            items = [f for f in items if f["topic"] == topic]
        if status:
            items = [f for f in items if f["status"] == status]
        if source_id:
            items = [f for f in items if f["source_id"] == str(source_id)]
        if query:
            items = [f for f in items if query.lower() in f["content"].lower()]
        return items[offset : offset + limit], len(items)

    def update_fact(self, fact_id, *, content=None, citation=None, published_date=None, embedding=None):
        f = self.facts.get(str(fact_id))
        if not f:
            return None
        if content is not None:
            f["content"] = content
        if citation is not None:
            f["citation"] = citation
        if embedding is not None:
            f["has_embedding"] = True
        return f

    def update_fact_status(self, fact_id, status):
        f = self.facts.get(str(fact_id))
        if not f:
            return None
        f["status"] = status
        return f

    def batch_update_fact_status(self, fact_ids, status):
        cnt = 0
        for fid in fact_ids:
            f = self.facts.get(str(fid))
            if f:
                f["status"] = status
                cnt += 1
        return cnt

    def delete_fact(self, fact_id):
        return self.facts.pop(str(fact_id), None) is not None

    def get_stats(self):
        return {"total_sources": len(self.sources), "totals": {"total": len(self.facts)}, "by_topic": {}}


def _build_client(monkeypatch) -> tuple[TestClient, _FakeStore]:
    store = _FakeStore()
    monkeypatch.setattr(kb_router, "_get_store", lambda: store)
    monkeypatch.setattr(kb_router, "_encode_texts", lambda texts: [[0.1] * 4 for _ in texts])
    app = FastAPI()
    app.include_router(kb_router.router)
    return TestClient(app), store


def test_knowledge_base_create_approve_and_delete_flow(monkeypatch):
    client, store = _build_client(monkeypatch)

    # 1. Create source with raw_text -> chunked into pending facts
    create_resp = client.post(
        "/rag/knowledge-base/sources",
        json={
            "topic": "education",
            "source_type": "document",
            "title": "Báo cáo UNESCO 2025",
            "url": "https://example.org/unesco",
            "raw_text": "Tỷ lệ biết chữ đạt 95%. Đầu tư giáo dục tăng 12% mỗi năm. Học trực tuyến mở rộng nhanh.",
            "auto_approve": False,
        },
    )
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["status"] == "pending"
    assert created["created_facts"] == 1
    assert store.committed is True

    # 2. List pending facts
    facts_resp = client.get("/rag/knowledge-base/facts", params={"topic": "education", "status": "pending"})
    assert facts_resp.status_code == 200
    facts_data = facts_resp.json()
    assert facts_data["total"] == 1
    fact_id = facts_data["items"][0]["id"]

    # 3. Approve fact
    approve_resp = client.patch(f"/rag/knowledge-base/facts/{fact_id}/status", json={"status": "approved"})
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "approved"

    # 4. Update fact content
    patch_resp = client.patch(
        f"/rag/knowledge-base/facts/{fact_id}",
        json={"content": "Tỷ lệ biết chữ toàn cầu đạt 95% theo UNESCO 2025."},
    )
    assert patch_resp.status_code == 200
    assert "95%" in patch_resp.json()["content"]

    # 5. Stats & delete source
    stats_resp = client.get("/rag/knowledge-base/stats")
    assert stats_resp.status_code == 200
    assert stats_resp.json()["total_sources"] == 1

    del_resp = client.delete(f"/rag/knowledge-base/sources/{created['source_id']}")
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True
    assert len(store.facts) == 0


def test_knowledge_base_validation_and_404(monkeypatch):
    client, _ = _build_client(monkeypatch)

    bad_req = client.post("/rag/knowledge-base/sources", json={"topic": "education"})
    assert bad_req.status_code == 400

    missing_fact = client.patch(f"/rag/knowledge-base/facts/{uuid4()}/status", json={"status": "approved"})
    assert missing_fact.status_code == 404

