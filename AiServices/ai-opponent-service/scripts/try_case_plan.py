"""
Script THU CONG: goi LLM THAT de xem case file sinh ra — KHONG can DB, KHONG luu gi.
Ton token that -> khong nam trong pytest.

Chay tu thu muc goc service:
    python -m scripts.try_case_plan "Học sinh không nên có bài tập về nhà" --ai-side con --difficulty hard
"""
import argparse
import asyncio
import json
import sys

from app.core.config import get_settings
from app.llm.client import get_llm_client
from app.opponent.models import DebateSide, OpponentDifficulty
from app.opponent.service import generate_case_file


async def main() -> int:
    parser = argparse.ArgumentParser(description="Thu Case Planning voi LLM that")
    parser.add_argument("motion")
    parser.add_argument(
        "--ai-side", choices=[s.value for s in DebateSide], default="con", help="Phe AI (learner = phe con lai)"
    )
    parser.add_argument("--difficulty", choices=[d.value for d in OpponentDifficulty], default="medium")
    parser.add_argument("--show-prompt", action="store_true", help="In ca system/user prompt")
    parser.add_argument("--no-review", action="store_true", help="Tat Stance Reviewer")
    args = parser.parse_args()

    # In lai motion DA NHAN (khong phai dong lenh console hien thi): console Windows khong phai UTF-8
    # co the lam mat dau khi truyen tham so. ascii() in ma \u.. — doc duoc ke ca khi console hien sai.
    print(f"Motion (da nhan): {args.motion}")
    print(f"Motion (ascii):   {ascii(args.motion)}")
    if "?" in args.motion or chr(0xFFFD) in args.motion:
        print("CANH BAO: motion co ky tu '?' / '\\ufffd' — co the da mat dau khi truyen tu console. "
              "Dat console ve UTF-8 (chcp 65001) hoac PYTHONIOENCODING=utf-8 roi chay lai.")

    settings = get_settings()
    client = get_llm_client(settings)
    print(f"Provider: {client.provider} | model: {client.model} | temperature: {settings.case_plan_temperature}")
    reviewer_client = None
    if settings.stance_review_enabled and not args.no_review:
        reviewer_client = get_llm_client(
            settings, provider=settings.stance_review_provider, model=settings.stance_review_model
        )
    print(f"Stance reviewer: {reviewer_client.provider + '/' + reviewer_client.model if reviewer_client else 'TAT'}")

    ai_side = DebateSide(args.ai_side)
    learner_side = DebateSide.PRO if ai_side == DebateSide.CON else DebateSide.CON
    outcome = await generate_case_file(
        args.motion, ai_side, learner_side, OpponentDifficulty(args.difficulty), client, settings, reviewer_client
    )

    if args.show_prompt:
        print("\n===== SYSTEM PROMPT =====\n" + outcome.system_prompt)
        print("\n===== USER PROMPT =====\n" + outcome.attempts[0].user_prompt)

    for a in outcome.attempts:
        status = "OK" if a.success else f"LOI [{a.failure_kind}]: {a.error}"
        print(f"\nLan {a.attempt} [{a.purpose.value}] ({a.latency_ms} ms): {status}")
        if a.retry_feedback:
            print("  Phan hoi gui cho lan thu ke tiep:\n    " + a.retry_feedback.replace("\n", "\n    "))
        if a.reviewer_verdict is not None and a.reviewer_detail is not None:
            print(f"  Stance review: {a.reviewer_verdict.value}")
            for item in a.reviewer_detail.get("positions", []):
                print(f"    {item['id']}: {item['position']} — {item['reason']}")
            if "reviewer_error" in a.reviewer_detail:
                print(f"    reviewer loi: {a.reviewer_detail['reviewer_error']}")
        if not a.success and a.raw_output:
            print("Raw output:\n" + a.raw_output)  # khong cat: can ban day du lam bang chung

    if outcome.case_file is None:
        print("\n=> THAT BAI, khong co case file hop le.")
        return 1

    print(f"\n===== CASE FILE ({outcome.prompt_version}) =====")
    print(json.dumps(outcome.case_file.model_dump(), ensure_ascii=False, indent=2))

    # Chi canh bao, khong reject — cung danh sach duoc luu vao opponent_llm_calls.vague_evidence.
    final_plan = next(a for a in reversed(outcome.attempts) if a.purpose.value == "case_plan" and a.success)
    vague = final_plan.vague_evidence
    print("\n===== BANG CHUNG MO HO =====")
    print("\n".join(f'"{v["phrase"]}" @ {v["field"]}' for v in vague) if vague else "(khong phat hien cum nao)")
    return 0


if __name__ == "__main__":
    # In tieng Viet co dau ra console Windows khong bi loi encoding
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(asyncio.run(main()))
