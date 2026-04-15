"""
=============================================================================
RG Abbreviation Expander
=============================================================================
Reads one or more RG JSON files, expands Latin abbreviations in all
header and subentry texts, and writes new JSON files.

Expansion format:
    benef.  →  benef. [beneficium / beneficialis]
    acc.    →  acc. [accipere / acceptus / acceptatio]

Key behaviours:
  - Substitutions applied longest-first to avoid partial matches
    (e.g. "benef. c. c. vel s. c." is caught before "benef.")
  - Idempotent: already-expanded terms (containing "[") are not re-substituted
  - Original text preserved in "text_original" field alongside "text"
  - Folio references (108v., 52v.) are NOT touched

Usage:
    # Single file
    python rg_expand_abbreviations.py --input rg1.json --output rg1_expanded.json

    # Multiple files (glob)
    python rg_expand_abbreviations.py --input "data/*.json" --output-dir expanded/

    # Multiple explicit files
    python rg_expand_abbreviations.py --input rg1.json rg2.json --output-dir expanded/

    # Show every substitution made (debug)
    python rg_expand_abbreviations.py --input rg1.json --output out.json --verbose

Dependencies:
    pip install tqdm    # optional, for progress bar
=============================================================================
"""

import argparse
import glob
import json
import re
import sys
from pathlib import Path

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False


# ---------------------------------------------------------------------------
# Build substitution list
# ---------------------------------------------------------------------------

def build_substitution_list(abbrev_dict: dict) -> list:
    """
    Returns list of (abbrev, expanded_form, compiled_regex)
    sorted by abbreviation length DESCENDING.
    """
    substitutions = []
    for abbrev, translations in abbrev_dict.items():
        if not abbrev.strip():
            continue

        expansion     = " / ".join(translations)
        expanded_form = f"{abbrev} [{expansion}]"

        # Match only when preceded by whitespace, '(', '[', or start-of-string
        # and followed by whitespace, ',', ')', ']', or end-of-string.
        # This prevents "a." matching inside "abbat." and ensures compound
        # abbreviations like "benef. c. c. vel s. c." win over "benef.".
        pattern = re.compile(
            r'(?:(?<=\s)|(?<=\()|(?<=\[)|^)'
            + re.escape(abbrev)
            + r'(?=\s|,|\)|\]|$)',
            re.MULTILINE | re.UNICODE,
        )
        substitutions.append((abbrev, expanded_form, pattern))

    # Longest-first: compound abbreviations are matched before their parts
    substitutions.sort(key=lambda x: len(x[0]), reverse=True)
    return substitutions


# ---------------------------------------------------------------------------
# Expand a single text string
# ---------------------------------------------------------------------------

def expand_text(text: str, substitutions: list) -> tuple:
    """
    Apply all substitutions to text.
    Returns (expanded_text, list_of_change_descriptions).

    Idempotency: if '<abbrev> [' already appears in the text, that
    abbreviation is skipped (prevents double-expansion on re-runs).
    """
    result  = text
    applied = []

    for abbrev, expanded_form, pattern in substitutions:
        # Skip if this abbreviation was already expanded
        if abbrev + " [" in result:
            continue

        new_result, n = pattern.subn(expanded_form, result)
        if n > 0:
            result = new_result
            applied.append(f"{abbrev!r} -> {expanded_form!r}  ({n}x)")

    return result, applied


# ---------------------------------------------------------------------------
# Process a full RG JSON dict
# ---------------------------------------------------------------------------

def process_rg_data(data: dict, substitutions: list, verbose: bool) -> tuple:
    """
    Expand abbreviations in every header and subentry text.

    Returns:
        new_data : dict with same structure; each text field gets
                   a companion 'text_original' field
        stats    : summary counts
    """
    stats = dict(
        total_records=0,
        records_changed=0,
        total_subentries=0,
        total_expansions=0,
    )

    new_data   = {}
    records    = list(data.items())
    iterator   = tqdm(records, desc="Records") if HAS_TQDM else records

    for rg_id, entry in iterator:
        stats["total_records"] += 1
        new_entry   = {}
        any_change  = False

        # Header
        header     = entry.get("header", {})
        header_txt = header.get("text", "").strip()
        if header_txt:
            expanded, changes = expand_text(header_txt, substitutions)
            new_entry["header"] = {
                "text":          expanded,
                "text_original": header_txt,
            }
            if changes:
                any_change = True
                stats["total_expansions"] += len(changes)
                if verbose:
                    for c in changes:
                        print(f"  [{rg_id}] header  {c}")
        else:
            new_entry["header"] = header.copy()

        # Subentries
        new_subs = {}
        for sub_id, sub in entry.get("subentries", {}).items():
            stats["total_subentries"] += 1
            sub_txt = sub.get("text", "").strip()
            if sub_txt:
                expanded, changes = expand_text(sub_txt, substitutions)
                new_subs[sub_id] = {
                    "text":          expanded,
                    "text_original": sub_txt,
                }
                if changes:
                    any_change = True
                    stats["total_expansions"] += len(changes)
                    if verbose:
                        for c in changes:
                            print(f"  [{rg_id}-{sub_id}] {c}")
            else:
                new_subs[sub_id] = sub.copy()

        new_entry["subentries"] = new_subs

        # Preserve any extra top-level fields
        for k, v in entry.items():
            if k not in ("header", "subentries"):
                new_entry[k] = v

        new_data[rg_id] = new_entry
        if any_change:
            stats["records_changed"] += 1

    return new_data, stats


# ---------------------------------------------------------------------------
# Process one file
# ---------------------------------------------------------------------------

def process_file(input_path: Path, output_path: Path,
                 substitutions: list, verbose: bool) -> None:
    print(f"\n-> {input_path.name}")

    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        print(f"   Warning: Skipping — expected a JSON object, got {type(data).__name__}")
        return

    expanded, stats = process_rg_data(data, substitutions, verbose)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(expanded, f, ensure_ascii=False, indent=2)

    pct = 100 * stats["records_changed"] / max(stats["total_records"], 1)
    print(f"   {stats['records_changed']:,} / {stats['total_records']:,} "
          f"records changed ({pct:.1f}%)")
    print(f"   {stats['total_expansions']:,} expansions across "
          f"{stats['total_subentries']:,} subentries")
    print(f"   Written -> {output_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Expand Latin abbreviations in RG JSON files"
    )
    parser.add_argument(
        "--input", nargs="+", required=True,
        help="Input JSON file(s) or glob pattern, e.g. 'data/*.json'",
    )
    parser.add_argument(
        "--abbrev", default="abrev.json",
        help="Abbreviations JSON file (default: abrev.json)",
    )
    parser.add_argument(
        "--output", default=None,
        help="Output path — only for single-file mode",
    )
    parser.add_argument(
        "--output-dir", default="expanded",
        help="Output directory for multi-file mode (default: expanded/)",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print every substitution as it is applied",
    )
    args = parser.parse_args()

    # Load abbreviations
    abbrev_path = Path(args.abbrev)
    if not abbrev_path.exists():
        print(f"Error: Abbreviations file not found: {abbrev_path}")
        sys.exit(1)

    with open(abbrev_path, encoding="utf-8") as f:
        abbrev_dict = json.load(f)

    substitutions = build_substitution_list(abbrev_dict)

    print(f"Loaded {len(abbrev_dict)} abbreviations from {abbrev_path}")
    print(f"Built {len(substitutions)} patterns (sorted longest-first)")
    print(f"  Longest : {substitutions[0][0]!r}  ({len(substitutions[0][0])} chars)")
    print(f"  Shortest: {substitutions[-1][0]!r}  ({len(substitutions[-1][0])} chars)")

    # Resolve input files (support globs)
    input_files = []
    for pattern in args.input:
        matched = glob.glob(pattern)
        if matched:
            input_files.extend(Path(p) for p in matched)
        else:
            p = Path(pattern)
            if p.exists():
                input_files.append(p)
            else:
                print(f"  Warning: No files matched: {pattern}")

    input_files = sorted(set(input_files))

    if not input_files:
        print("Error: No input files found.")
        sys.exit(1)

    print(f"{len(input_files)} file(s) to process")

    # Dispatch
    if len(input_files) == 1 and args.output:
        process_file(input_files[0], Path(args.output),
                     substitutions, args.verbose)
    else:
        out_dir = Path(args.output_dir)
        for input_path in input_files:
            output_path = out_dir / (input_path.stem + "_expanded.json")
            process_file(input_path, output_path, substitutions, args.verbose)
        print(f"\nAll done. Output directory: {out_dir}/")


if __name__ == "__main__":
    main()