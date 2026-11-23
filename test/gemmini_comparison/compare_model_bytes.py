#!/usr/bin/env python3
"""Compare actual model, input, output, and recorded tensor bytes between runs."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


if not __debug__:
    raise SystemExit("Run this comparison with Python assertions enabled; remove -O or -OO.")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_audit(path):
    document = json.loads(path.read_text())
    assert document["summary"]["all_passed"]
    assert document["summary"]["result_count"] == 16
    entries = {
        (entry["model_id"], entry["sample_index"], entry["kind"]): entry
        for entry in document["entries"]
    }
    assert len(entries) == 16
    return document, entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--reference-results-root", type=Path,
                        help="Override the results directory recorded in the reference audit")
    parser.add_argument("--current-results-root", type=Path,
                        help="Override the results directory recorded in the current audit")
    args = parser.parse_args()
    reference, reference_entries = read_audit(args.reference)
    current, current_entries = read_audit(args.current)
    assert reference_entries.keys() == current_entries.keys()
    reference_root = (args.reference_results_root or Path(reference["results_root"])).resolve()
    current_root = (args.current_results_root or Path(current["results_root"])).resolve()
    records = []
    counts = Counter()
    for key in sorted(reference_entries):
        old = reference_entries[key]
        new = current_entries[key]
        reference_dir = (reference_root / old["path"]).parent
        current_dir = (current_root / new["path"]).parent
        files = [
            ("output", "output.bin"),
            ("model", "model_after.bin"),
            ("input", "input_after.bin"),
        ]
        assert old["verified_tensors"] == new["verified_tensors"]
        files.extend(
            ("tensor", f"tensors/tensor_{tensor['ordinal']}.bin")
            for tensor in old["verified_tensors"]
        )
        for category, name in files:
            old_bytes = (reference_dir / name).read_bytes()
            new_bytes = (current_dir / name).read_bytes()
            assert old_bytes == new_bytes, (key, name)
            counts[category] += 1
            records.append({
                "model_id": key[0],
                "sample_index": key[1],
                "kind": key[2],
                "file": name,
                "category": category,
                "bytes": len(new_bytes),
                "sha256": sha256(new_bytes),
            })
    assert counts == {"output": 16, "model": 16, "input": 16, "tensor": 136}
    result = {
        "passed": True,
        "comparison_script_sha256": sha256(Path(__file__).read_bytes()),
        "reference_results_root": str(reference_root),
        "current_results_root": str(current_root),
        "reference_audit": str(args.reference.resolve()),
        "reference_audit_sha256": sha256(args.reference.read_bytes()),
        "current_audit": str(args.current.resolve()),
        "current_audit_sha256": sha256(args.current.read_bytes()),
        "matching_file_count": len(records),
        "matching_file_counts": dict(counts),
        "matching_bytes": sum(record["bytes"] for record in records),
        "records": records,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "records"}, indent=2))


if __name__ == "__main__":
    main()
