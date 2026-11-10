"""
Ap luat verify HIEN TAI len output LLM da luu cua cac file ket qua, KHONG goi LLM (dev log muc 3.22).

Moi file trong docs/rag_results duoc tach thanh cac "lo" claim theo dung cach script goc da gui verify (eval_verify:
5 dong / lo, chi claim co fact; eval_evidence_pairs / eval_evidence_stability: 1 lap luan / lo). Lo duoc ghep voi lo
verify trong audit log (logs/eval_audit.jsonl*, prompt + raw output) co CUNG danh sach claim, do NGUOC tu thoi diem file
duoc ghi (ten file la gio dia phuong UTC+7), de lay dung lan chay. Ket qua: nhan moi cua tung claim theo code hien tai.

Hai che do:
    python scripts/rag/reapply_all_results.py --snapshot data/results/reapply_before.json
    python scripts/rag/reapply_all_results.py --snapshot data/results/reapply_after.json --compare data/results/reapply_before.json

Output chi co "fact_ids" (truoc khi co "details", muc 3.20) khong parse duoc voi code hien tai: bao la khong ap duoc.
"""
import argparse
import glob
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVICE_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.rag.verifier import NO_FACT_REASON, VERIFY_BATCH_SIZE, _build_batch_results
from app.services.json_utils import EvaluationParseError, extract_json
from reapply_verify_rules import parse_prompt

AUDIT_GLOB = str(SERVICE_DIR / "logs" / "eval_audit.jsonl*")
RESULTS = SERVICE_DIR / "docs" / "rag_results"
LOCAL_OFFSET = timedelta(hours=7)  # Ten file ket qua ghi gio dia phuong
FILES = (
    "verify_retrieve_20261108_115856.json",
    "verify_retrieve_20261108_144957.json",
    "evidence_pairs_rag_on_20261108_165841.json",
    "evidence_stability_20261108_172832.json",
)


def _file_end_utc(name: str) -> datetime:
    stamp = "_".join(name.removesuffix(".json").split("_")[-2:])
    local = datetime.strptime(stamp, "%Y%m%d_%H%M%S")
    # +5 s: lo cuoi duoc ghi audit ngay truoc khi file ket qua duoc ghi, cung giay
    return (local - LOCAL_OFFSET).replace(tzinfo=timezone.utc) + timedelta(seconds=5)


def units_of(name: str) -> list[dict]:
    """Cac lo claim (theo dung thu tu gui verify) cua 1 file ket qua, kem nhan da luu va nhan dung neu co."""
    data = json.loads((RESULTS / name).read_text(encoding="utf-8"))
    units = []
    if name.startswith("verify_"):
        rows = data["predictions"]
        for start in range(0, len(rows), VERIFY_BATCH_SIZE):
            batch = [r for r in rows[start:start + VERIFY_BATCH_SIZE]
                     if r["predicted"] != "ERROR" and r["reason"] != NO_FACT_REASON]
            if batch:
                units.append({"claims": [r["claim"] for r in batch],
                              "meta": [{"id": f"{r['set']}:{r['claim_id']}", "gold": r["expected"], "version": None,
                                        "stored": r["predicted"]} for r in batch]})
        return units
    records = data["records"]
    for record in records:
        if "error" in record:
            continue
        key = record.get("key") or f"{record['pair_id']}:{record['version']}"
        claims = record["claims"] if "claims" in record else record["evidence_check"]["claims"]
        sent = [c for c in claims if c["reason"] != NO_FACT_REASON]
        version = key.split(":")[-1]
        if sent:
            units.append({"claims": [c["claim"] for c in sent],
                          "meta": [{"id": f"{key}:{i}", "gold": None, "version": version, "stored": c["label"]}
                                   for i, c in enumerate(sent)]})
    return units


def load_audit() -> list[dict]:
    rows = []
    for path in glob.glob(AUDIT_GLOB):
        for line in open(path, encoding="utf-8"):
            record = json.loads(line)
            if record["label"] == "rag_verify" and record["error"] is None and record["raw_output"]:
                rows.append(record)
    rows.sort(key=lambda r: r["ts"])
    return rows


def reapply(name: str, audit: list[dict]) -> dict:
    units = units_of(name)
    end = _file_end_utc(name)
    candidates = [row for row in audit if datetime.fromisoformat(row["ts"]) <= end]
    prompts = [parse_prompt(row["user_prompt"]) for row in candidates]
    cursor = len(candidates) - 1
    labels, unmatched, unparsable = {}, 0, 0
    for unit in reversed(units):
        found = cursor
        while found >= 0 and prompts[found][0] != unit["claims"]:
            found -= 1
        if found < 0:  # Khong ghep duoc: giu cursor cho cac lo truoc do
            unmatched += 1
            continue
        cursor = found
        claims, facts = prompts[cursor]
        try:
            results = _build_batch_results(extract_json(candidates[cursor]["raw_output"]), claims, facts)
        except EvaluationParseError:
            unparsable += 1
            results = None
        cursor -= 1
        if results is None:
            continue
        for meta, result in zip(unit["meta"], results):
            labels[meta["id"]] = {**meta, "label": result.label.value,
                                  "dropped_fact_ids": getattr(result, "dropped_fact_ids", [])}
    return {"units": len(units), "unmatched_units": unmatched, "unparsable_units": unparsable, "claims": labels}


def stats(claims: dict) -> dict:
    values = list(claims.values())
    return {
        "claims": len(values),
        "contradicted_true": sum(c["label"] == "CONTRADICTED" and c["version"] == "true" for c in values),
        "contradicted_fake": sum(c["label"] == "CONTRADICTED" and c["version"] == "fake" for c in values),
        "false_contradiction": sum(c["label"] == "CONTRADICTED" and c["gold"] in ("SUPPORTED", "NOT_FOUND") for c in values),
        "true_contradiction": sum(c["label"] == "CONTRADICTED" and c["gold"] == "CONTRADICTED" for c in values),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--compare", type=Path, default=None, help="Snapshot truoc khi doi luat")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    audit = load_audit()
    snapshot = {name: reapply(name, audit) for name in FILES}
    args.snapshot.parent.mkdir(parents=True, exist_ok=True)
    args.snapshot.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, data in snapshot.items():
        print(f"{name}: {data['units']} lo, khong ghep {data['unmatched_units']}, khong parse {data['unparsable_units']}, "
              f"{len(data['claims'])} claim ap duoc | {stats(data['claims'])}")

    if args.compare:
        before = json.loads(args.compare.read_text(encoding="utf-8"))
        print("\n| File | Claim ap duoc | Doi nhan | CONTRADICTED ban that (truoc -> sau) | CONTRADICTED ban bia | "
              "False contradiction (gold S/N) | True contradiction (gold C) |")
        print("|---|---|---|---|---|---|---|")
        for name in FILES:
            old, new = before[name]["claims"], snapshot[name]["claims"]
            common = sorted(set(old) & set(new))
            changed = [k for k in common if old[k]["label"] != new[k]["label"]]
            s_old, s_new = stats({k: old[k] for k in common}), stats({k: new[k] for k in common})
            print(f"| {name} | {len(common)} | {len(changed)} | {s_old['contradicted_true']} -> {s_new['contradicted_true']} | "
                  f"{s_old['contradicted_fake']} -> {s_new['contradicted_fake']} | "
                  f"{s_old['false_contradiction']} -> {s_new['false_contradiction']} | "
                  f"{s_old['true_contradiction']} -> {s_new['true_contradiction']} |")
            for k in changed:
                print(f"    {k}: {old[k]['label']} -> {new[k]['label']} (gold {new[k]['gold']}, ban {new[k]['version']}, "
                      f"bo id {new[k]['dropped_fact_ids']})")


if __name__ == "__main__":
    main()
