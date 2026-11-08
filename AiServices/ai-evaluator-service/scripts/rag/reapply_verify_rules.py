"""
Ap lai luat verify hien tai len output LLM DA LUU, KHONG goi LLM (dev log muc 3.21.3).

Nguon: audit log (logs/eval_audit.jsonl*, label "rag_verify") giu nguyen user prompt (claim + fact_id + noi dung fact)
va raw output (details, cited_facts co stance) cua moi lo verify. Script dung lai danh sach claim/fact tu prompt, chay
`_build_batch_results` cua app/rag/verifier.py voi luat hien tai, roi ghep voi tung lap luan cua file ket qua do on
dinh (`--stability`) theo dung thu tu va dung danh sach claim. Lo nao khong ghep duoc (vd lan uoc tinh truoc dot do)
thi bo qua va bao lai. Sau do ap `adjust_evidence` tren diem goc cua lan chay D nhu eval_evidence_stability.py.

Chi dung duoc voi output co stance ("cited_facts", tu muc 3.21.2); output cu chi co fact_ids thi khong du du lieu.

Cach dung:
    python scripts/rag/reapply_verify_rules.py
"""
import argparse
import glob
import json
import re
import shutil
import statistics
import sys
from datetime import datetime
from pathlib import Path
from uuid import UUID

SERVICE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVICE_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.rag.schemas import RetrievedFact
from app.rag.verifier import NO_FACT_REASON, _build_batch_results
from app.services.json_utils import extract_json
from eval_evidence_stability import DEFAULT_BASE, VERSIONS, load_base, run_metrics

sys.stdout.reconfigure(encoding="utf-8")

AUDIT_GLOB = str(SERVICE_DIR / "logs" / "eval_audit.jsonl*")
DEFAULT_STABILITY = SERVICE_DIR / "docs" / "rag_results" / "evidence_stability_20261108_172832.json"
RESULTS_DIR = SERVICE_DIR / "data" / "results"
DOCS_RESULTS_DIR = SERVICE_DIR / "docs" / "rag_results"

_BLOCK = re.compile(r"\[CLAIM (\d+)\]\n(.*?)\n\[FACT CUA CLAIM \1\]\n(.*?)(?=\n\n\[CLAIM \d+\]\n|\Z)", re.DOTALL)
_FACT = re.compile(r"- fact_id: ([0-9a-f-]{36})\n  noi dung: (.*?)(?=\n- fact_id: |\Z)", re.DOTALL)


def parse_prompt(user_prompt: str) -> tuple[list[str], list[list[RetrievedFact]]]:
    """Claim va fact cua tung claim tu user prompt verify (app/rag/prompts.build_verify_prompt)."""
    claims, facts = [], []
    # Lan retry co them dong [NHAC LAI] o cuoi
    prompt = user_prompt.split("\n\n[NHAC LAI]")[0]
    for _, claim, block in _BLOCK.findall(prompt):
        claims.append(claim)
        facts.append([RetrievedFact(fact_id=UUID(fid), content=content.strip(), score=0.0) for fid, content in _FACT.findall(block)])
    return claims, facts


def load_audit_batches() -> list[dict]:
    rows = []
    for path in glob.glob(AUDIT_GLOB):
        for line in open(path, encoding="utf-8"):
            record = json.loads(line)
            if record["label"] == "rag_verify" and record["error"] is None and '"cited_facts"' in (record["raw_output"] or ""):
                rows.append(record)
    rows.sort(key=lambda r: r["ts"])
    batches = []
    for row in rows:
        claims, facts = parse_prompt(row["user_prompt"])
        results = _build_batch_results(extract_json(row["raw_output"]), claims, facts)
        batches.append({"ts": row["ts"], "claims": claims, "results": results})
    return batches


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stability", type=Path, default=DEFAULT_STABILITY)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    args = parser.parse_args()

    stability = json.loads(args.stability.read_text(encoding="utf-8"))
    base = load_base(args.base)
    batches = load_audit_batches()
    print(f"{len(batches)} lo verify co stance trong audit log")

    records = {r["key"]: json.loads(json.dumps(r)) for r in stability["records"]}
    cursor, skipped, changed = 0, [], []
    for key in (r["key"] for r in stability["records"]):
        record = records[key]
        llm_claims = [c for c in record["claims"] if c["reason"] != NO_FACT_REASON]
        if not llm_claims:
            continue
        wanted = [c["claim"] for c in llm_claims]
        while cursor < len(batches) and batches[cursor]["claims"] != wanted:
            skipped.append(batches[cursor]["ts"])
            cursor += 1
        if cursor >= len(batches):
            raise SystemExit(f"Khong tim thay lo verify cho {key}: output da luu khong du de ap luat")
        for claim, result in zip(llm_claims, batches[cursor]["results"]):
            new_label = result.label.value
            if new_label != claim["label"]:
                changed.append({"key": key, "claim": claim["claim"], "old": claim["label"], "new": new_label,
                                "details": [(d.detail, [result.fact_stances.get(f, "?") for f in d.fact_ids]) for d in result.details]})
            claim["label"] = new_label
        cursor += 1

    pair_ids = sorted({key.split(":")[1] for key in records}, key=lambda p: [r["key"] for r in stability["records"]].index(f"1:{p}:true"))
    runs = sorted({int(key.split(":")[0]) for key in records})
    new_runs = [run_metrics(run, records, base, pair_ids) for run in runs]
    old_runs = stability["runs"]

    print(f"Bo qua {len(skipped)} lo khong thuoc dot do on dinh: {skipped}")
    print("\n| Luat | Lan | Evidence that | Evidence bia | Chenh TB | Wilcoxon exact p | That bi tru | Bia bi phat hien | Claim CONFLICTING |")
    print("|---|---|---|---|---|---|---|---|---|")
    for name, rows in (("cu (claim)", old_runs), ("moi (chi tiet)", new_runs)):
        for r in rows:
            p = f"{r['wilcoxon']['p_exact']:.6f}" if r["wilcoxon"] else "-"
            print(f"| {name} | {r['run']} | {r['evidence_mean_true']} | {r['evidence_mean_fake']} | {r['mean_diff']} | {p} | "
                  f"{r['true_penalized']} | {r['fake_detected']}/15 | {r['conflicting_claims']} |")
    for r in new_runs:
        print(f"moi lan {r['run']}: bia khong bi phat hien {r['fake_not_detected']}")
        for item in r["penalized_detail"]:
            print(f"  THAT BI TRU {item['pair_id']} {item['before']} -> {item['after']}")
            for claim in item["claims"]:
                print(f"    claim: {claim['claim']}\n    ly do: {claim['reason']}")
    print(f"\n{len(changed)} claim doi nhan:")
    for c in changed:
        print(f"  {c['key']} {c['old']} -> {c['new']} | {c['claim'][:110]} | chi tiet: {c['details']}")

    output = {"rules": "v4_detail_conflict", "stability_file": args.stability.name, "base_file": args.base.name,
              "runs_old": old_runs, "runs_new": new_runs, "changed_claims": changed, "skipped_batches": skipped}
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RESULTS_DIR / f"evidence_stability_reapplied_{datetime.now():%Y%m%d_%H%M%S}.json"
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    DOCS_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output_path, DOCS_RESULTS_DIR / output_path.name)
    print(f"\nDa ghi {output_path} va chep sang {DOCS_RESULTS_DIR / output_path.name}")


if __name__ == "__main__":
    main()
