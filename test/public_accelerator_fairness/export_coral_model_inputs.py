#!/usr/bin/env python3
"""保存已验证的 Coral 模型输入及相对路径源码摘要。"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess

from run_coral_fair import ARCHIVE_SHA, CORAL_COMMIT, read, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coral-work", type=Path, required=True)
    parser.add_argument("--comparison-root", type=Path, required=True)
    parser.add_argument("--comparison-archive", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    for key, value in vars(args).items():
        setattr(args, key, value.resolve())
    assert sha(args.comparison_archive) == ARCHIVE_SHA
    upstream = read(args.comparison_root / "coral/UPSTREAM.json")
    assert upstream["commit"] == CORAL_COMMIT
    source = args.coral_work / "coralnpu"
    commit = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    assert commit == CORAL_COMMIT
    original = args.coral_work / "coral_build/sim_build.json"
    record = read(original)
    assert record["passed"] and record["source_commit"] == CORAL_COMMIT
    assert "Verilator 5.054 " in record["verilator"]
    for path, expected in record["source_sha256"].items():
        relative = path.split("/public_accelerator_work/", 1)[-1]
        assert sha(args.coral_work / relative) == expected
    paths = list((args.comparison_root / "coral/upstream").rglob("*"))
    comparison = {}
    for path in sorted(paths):
        if not path.is_file(): continue
        relative = path.relative_to(args.comparison_root / "coral/upstream")
        checksum = sha(path)
        assert sha(source / relative) == checksum, relative
        comparison[str(path.relative_to(args.comparison_root))] = checksum
    pairs = {
        "coral/rtl/VmeCoreMiniAxi.sv": "coral_build/sources/VmeCoreMiniAxi.sv",
        "coral/rtl/vme_observation.vlt": "coral_build/sources/vme_observation.vlt",
        "coral/benchmark/coral_axi_benchmark.cpp": "coral_benchmark/coral_axi_benchmark.cpp",
        "coral/benchmark/shared_gemm_staged.elf": "coral_benchmark/shared_gemm_staged.elf",
    }
    for relative, old in pairs.items():
        checksum = sha(args.comparison_root / relative)
        assert sha(args.coral_work / old) == checksum, relative
        comparison[relative] = checksum
    comparison["coral/UPSTREAM.json"] = sha(args.comparison_root / "coral/UPSTREAM.json")
    assert comparison["coral/rtl/VmeCoreMiniAxi.sv"] == upstream["generated_rtl_sha256"]
    assert not args.out.exists() or not any(args.out.iterdir())
    args.out.mkdir(parents=True, exist_ok=True)
    objects = args.coral_work / "coral_build/obj"
    names = ["VVmeCoreMiniAxi__ALL.a", "verilated.o", "verilated_dpi.o",
             "verilated_threads.o", "sram_backdoor.o"]
    names += [path.name.removesuffix(".gz") for path in sorted(objects.glob("*.h.gz"))]
    assert len(names) >= 10
    files = {}
    for name in names:
        path = objects / (name + ".gz")
        content = gzip.decompress(path.read_bytes())
        files[name] = {"compressed_sha256": sha(path), "compressed_bytes": path.stat().st_size,
                       "uncompressed_sha256": hashlib.sha256(content).hexdigest(),
                       "uncompressed_bytes": len(content)}
        shutil.copy2(path, args.out / path.name)
    provenance = args.out / "provenance"
    provenance.mkdir()
    copied = {}
    for path in (original, args.coral_work / "coral_build/build_coral_model.py"):
        shutil.copy2(path, provenance / path.name)
        copied["provenance/" + path.name] = sha(path)
    runtime = args.reference_root / "tools/verilator/include"
    runtime_hashes = {str(path.relative_to(runtime)): sha(path)
                      for path in sorted(runtime.rglob("*.h")) if path.is_file()}
    manifest = {"format_version": 1, "source_commit": commit,
                "source_archive_sha256": ARCHIVE_SHA, "verilator": record["verilator"],
                "platform": {"system": platform.system(), "machine": platform.machine()},
                "comparison_source_sha256": comparison, "runtime_headers_sha256": runtime_hashes,
                "provenance_files_sha256": copied, "files": files,
                "model_bytes_compressed": sum(row["compressed_bytes"] for row in files.values()),
                "model_bytes_uncompressed": sum(row["uncompressed_bytes"] for row in files.values())}
    (args.out / "model_inputs.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": True, "model_files": len(files),
                      "comparison_source_files": len(comparison),
                      "compressed_bytes": manifest["model_bytes_compressed"],
                      "out": str(args.out)}, indent=2))


if __name__ == "__main__":
    main()
