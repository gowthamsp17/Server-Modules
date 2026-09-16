"""
combine_lsmod_csv.py

Combines any number of CSV files (given as file paths and/or glob patterns)
into a single output CSV (header taken once from the first file, all data
rows from all matching files appended after it, in the order given).

Usage:
    python3 combine_lsmod_csv.py -o OUTPUT.csv INPUT1.csv INPUT2.csv ...
    python3 combine_lsmod_csv.py -o OUTPUT.csv "some/glob/*.csv"

Both -o/--output and at least one input are required.
"""

import argparse
import glob
import sys


def resolve_files(patterns: list) -> list:
    files = []
    for pattern in patterns:
        matches = sorted(glob.glob(pattern))
        if not matches:
            raise ValueError(f"No files matched: {pattern}")
        files.extend(matches)
    return files


def combine(patterns: list, output_path: str):
    files = resolve_files(patterns)

    print(f"[*] Combining {len(files)} files:")
    for f in files:
        print(f"    - {f}")

    with open(output_path, 'w', newline='') as out_f:
        header_written = False
        for path in files:
            with open(path, 'r', newline='') as in_f:
                header = in_f.readline()
                if not header_written:
                    out_f.write(header)
                    header_written = True
                for line in in_f:
                    out_f.write(line)

    print(f"[✓] Saved: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Combine CSV files into one.")
    parser.add_argument('inputs', nargs='+',
                         help="Input CSV file paths and/or glob patterns.")
    parser.add_argument('-o', '--output', required=True,
                         help="Output CSV path.")
    args = parser.parse_args()

    combine(args.inputs, args.output)
