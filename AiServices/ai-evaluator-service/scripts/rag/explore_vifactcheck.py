"""
Xem cau truc that cua dataset ViFactCheck TRUOC khi viet filter: ten cot, dong mau, phan bo.
Chi doc va in ra, khong ghi gi vao DB.

Cach dung:
    python scripts/rag/explore_vifactcheck.py
"""
import sys
from collections import Counter
from pathlib import Path

from datasets import load_dataset

# In tieng Viet tren console Windows khong bi loi encoding
sys.stdout.reconfigure(encoding="utf-8")

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
MAIN_DATASET = "tranthaihoa/vifactcheck"
GOLD_DATASET = "tranthaihoa/vifactcheck_gold_evidence"

SAMPLE_ROWS = 2
PREVIEW_CHARS = 300
# Cot it gia tri (nhu topic, label) moi in phan bo; cot van ban dai se bi bo qua
MAX_DISTINCT_TO_PRINT = 100


def _preview(row: dict) -> dict:
    return {key: (f"{value[:PREVIEW_CHARS]}..." if isinstance(value, str) and len(value) > PREVIEW_CHARS else value)
            for key, value in row.items()}


def describe(dataset_dict) -> None:
    for split, split_data in dataset_dict.items():
        print(f"\n--- split={split}: {split_data.num_rows} dong")
        print(f"cot: {split_data.column_names}")
        print(f"kieu: {split_data.features}")
        for index in range(min(SAMPLE_ROWS, split_data.num_rows)):
            print(f"mau {index}: {_preview(split_data[index])}")


def print_distributions(dataset_dict) -> None:
    columns = next(iter(dataset_dict.values())).column_names
    for column in columns:
        total: Counter = Counter()
        per_split = {}
        for split, split_data in dataset_dict.items():
            values = split_data[column]
            if not values or not isinstance(values[0], (str, int, bool)):
                break
            per_split[split] = Counter(values)
            total.update(per_split[split])
        else:
            if len(total) > MAX_DISTINCT_TO_PRINT:
                print(f"\ncot {column}: {len(total)} gia tri khac nhau (khong in phan bo)")
                continue
            print(f"\ncot {column}: tong {dict(total.most_common())}")
            for split, counter in per_split.items():
                print(f"  {split}: {dict(counter.most_common())}")


def compare_columns(main, gold) -> None:
    for split in gold:
        if split not in main:
            print(f"split {split} chi co trong gold")
            continue
        main_columns = set(main[split].column_names)
        gold_columns = set(gold[split].column_names)
        print(f"\nsplit={split}: cot chung {sorted(main_columns & gold_columns)}, chi co o gold {sorted(gold_columns - main_columns)}")
        for column in sorted(main_columns & gold_columns):
            main_values = main[split][column]
            if main_values and isinstance(main_values[0], (str, int)):
                main_set, gold_set = set(main_values), set(gold[split][column])
                print(f"  {column}: main {len(main_set)} gia tri, gold {len(gold_set)}, trung {len(main_set & gold_set)}")


def main() -> None:
    print(f"=== {MAIN_DATASET} ===")
    main_data = load_dataset(MAIN_DATASET, cache_dir=str(DATA_DIR))
    describe(main_data)
    print_distributions(main_data)

    print(f"\n=== {GOLD_DATASET} ===")
    try:
        gold_data = load_dataset(GOLD_DATASET, cache_dir=str(DATA_DIR))
    except Exception as exc:  # Spec: dataset nay co the khong ton tai
        print(f"Khong tai duoc: {type(exc).__name__}: {exc}")
        return
    describe(gold_data)
    print_distributions(gold_data)
    print("\n=== Cach noi gold voi dataset chinh ===")
    compare_columns(main_data, gold_data)


if __name__ == "__main__":
    main()
