"""
Dau van tay cua cac file prompt / rubric / cong thuc trong app/ — de ket qua kiem tra gan voi DUNG cau hinh da test.

Hash = sha256 cua noi dung file (CRLF chuan hoa thanh LF de khong doi theo he dieu hanh). Hash tong hop = sha256 cua
cac dong "<duong dan>:<hash>" theo thu tu co dinh. Cac script cham diem ghi `config_hash` (hash tong hop) vao MOI ban ghi.

Chay:
    python scripts/config_fingerprint.py             # in hash tung file + hash tong hop
    python scripts/config_fingerprint.py --check HASH   # thoat != 0 neu hash tong hop khac HASH
"""
import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
# prompt / rubric / cong thuc: CHI cac file nay phai giu nguyen giua luc test va luc commit
FILES = [
    "app/prompts/evaluator_prompt.py",
    "app/prompts/round_prompt.py",
    "app/services/scoring.py",
    "app/services/evaluator.py",
    "app/services/round_evaluator.py",
]


def file_hashes() -> dict[str, str]:
    out = {}
    for rel in FILES:
        data = (ROOT / rel).read_bytes().replace(b"\r\n", b"\n")
        out[rel] = hashlib.sha256(data).hexdigest()
    return out


def combined_hash() -> str:
    lines = "\n".join(f"{rel}:{h}" for rel, h in file_hashes().items())
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", type=str, default=None, help="Hash tong hop ky vong")
    args = parser.parse_args()
    for rel, h in file_hashes().items():
        print(f"{h}  {rel}")
    combined = combined_hash()
    print(f"{combined}  COMBINED")
    if args.check is not None and args.check != combined:
        print(f"KHAC hash ky vong ({args.check})", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
