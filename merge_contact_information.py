from __future__ import annotations

import csv
from pathlib import Path


INPUT_DIR = Path("data/contact_information")
OUTPUT_FILE = INPUT_DIR / "all_contacts.csv"
EXPECTED_COLUMNS = ["lecture", "teacher", "first_name", "title", "gender", "mails"]


def iter_input_files(input_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in input_dir.iterdir()
        if path.is_file() and path.name != OUTPUT_FILE.name
    )


def normalize_row(row: dict[str, str]) -> dict[str, str]:
    normalized = {column: row.get(column, "") for column in EXPECTED_COLUMNS}
    if "." in normalized["first_name"]:
        normalized["first_name"] = "??"
    return normalized


def teacher_sort_key(row: dict[str, str]) -> tuple[str, str]:
    teacher = row["teacher"].strip()
    if not teacher:
        return ("", row["lecture"].casefold())

    parts = teacher.split()
    last_name = parts[-1].casefold()
    return (last_name, teacher.casefold())


def read_rows(input_files: list[Path]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    total_files = len(input_files)

    for index, input_file in enumerate(input_files, start=1):
        print(f"[{index}/{total_files}] Reading {input_file.name}")
        with input_file.open("r", encoding="utf-8", newline="") as csv_file:
            reader = csv.DictReader(csv_file, delimiter=";")
            file_rows = [normalize_row(row) for row in reader]
            rows.extend(file_rows)
        print(f"[{index}/{total_files}] Added {len(file_rows)} rows from {input_file.name}")
        print(f"Progress: total rows collected={len(rows)}")

    return rows


def write_rows(rows: list[dict[str, str]], output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=EXPECTED_COLUMNS, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    input_files = iter_input_files(INPUT_DIR)
    print(f"Found {len(input_files)} contact files in {INPUT_DIR}")

    rows = read_rows(input_files)
    rows.sort(key=teacher_sort_key)
    print(f"Writing {len(rows)} merged rows to {OUTPUT_FILE}")
    write_rows(rows, OUTPUT_FILE)
    print("Merge finished.")


if __name__ == "__main__":
    main()
