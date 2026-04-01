from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


RAW_HTML_DIR = Path("data/raw_html")
OUTPUT_DIR = Path("data/contact_information")
EXTRACT_SCRIPT = Path("extract_lectures.py")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run extract_lectures.py for every HTML file in data/raw_html."
    )
    parser.add_argument("--input-dir", type=Path, default=RAW_HTML_DIR, help="Directory with raw HTML files.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="Directory for generated CSV files.")
    return parser


def iter_input_files(input_dir: Path) -> list[Path]:
    return sorted(path for path in input_dir.iterdir() if path.is_file())


def run_extractor(input_file: Path, output_file: Path) -> int:
    command = [
        sys.executable,
        str(EXTRACT_SCRIPT),
        "--input",
        str(input_file),
        "--output",
        str(output_file),
    ]
    completed = subprocess.run(command, check=False)
    return completed.returncode


def main() -> None:
    args = build_arg_parser().parse_args()
    input_files = iter_input_files(args.input_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    total_files = len(input_files)
    processed_files = 0
    skipped_files = 0
    failed_files = 0

    print(f"Found {total_files} input files in {args.input_dir}")

    for index, input_file in enumerate(input_files, start=1):
        output_file = args.output_dir / input_file.name

        if input_file.stat().st_size == 0:
            skipped_files += 1
            print(f"[{index}/{total_files}] Skipping empty file: {input_file.name}")
            continue

        print(f"[{index}/{total_files}] Processing {input_file.name} -> {output_file.name}")
        return_code = run_extractor(input_file, output_file)

        if return_code == 0:
            processed_files += 1
            print(f"[{index}/{total_files}] Finished {input_file.name}")
        else:
            failed_files += 1
            print(f"[{index}/{total_files}] Failed {input_file.name} with exit code {return_code}")

        print(
            f"Progress: completed={processed_files}, skipped={skipped_files}, failed={failed_files}, total={total_files}"
        )

    print("Batch run finished.")
    print(f"Completed: {processed_files}")
    print(f"Skipped: {skipped_files}")
    print(f"Failed: {failed_files}")


if __name__ == "__main__":
    main()
