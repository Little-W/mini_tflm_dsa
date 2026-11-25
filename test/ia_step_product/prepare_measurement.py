#!/usr/bin/env python3
"""固定完整 IA 及依赖，分别测量 SoC 与紧凑存储扩展配置。"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import runpy
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/loaders/ia_loader.sv")
PARAMETERS = dict(DATA_WIDTH=16, SIZE=16, BUS_WIDTH=64, DMA_LANES=8,
                  REG_WIDTH=32, COUNT_WIDTH=29, CACHE_BLOCKS=32,
                  COMPACT_S8=0, ORDERED_JOB=1, RAM_WORD_ADDR_WIDTH=12,
                  PS_FRAME_COUNT=16, p_dma_source_layout=1,
                  p_shared_write_stage=1, p_register_dma_request=1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="3ff66f2b")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(["git", "rev-parse", args.reference + "^{commit}"],
                                       cwd=ROOT, text=True).strip()
    archive = subprocess.check_output(["git", "archive", revision, "rtl"], cwd=ROOT)
    resolve = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]
    cases, hashes = {}, {}
    with tempfile.TemporaryDirectory() as temporary:
        original = Path(temporary)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as source:
            source.extractall(original, filter="data")
        for label, root in (("reference", original), ("current", ROOT)):
            files, hashes[label] = [], {}
            common = sorted(path for path in (root / "rtl/common").rglob("*")
                            if path.suffix in (".sv", ".v"))
            for path in resolve([root / SOURCE] + common, root):
                relative = path.relative_to(root)
                target = out / label / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                data = path.read_bytes()
                target.write_bytes(data)
                files.append(str(relative))
                hashes[label][str(relative)] = hashlib.sha256(data).hexdigest()
            for profile, compact in (("soc", 0), ("compact", 1)):
                parameters = dict(PARAMETERS, COMPACT_S8=compact)
                cases[profile + "_" + label] = dict(
                    top="ia_loader", sources=files, parameters=parameters,
                    options=["-DSYNTHESIS=1", "-DXILINX_FPGA=1"] +
                            [f"-G{name}={value}" for name, value in parameters.items()],
                    configuration=("SoC: 32 regular slots" if not compact else
                                   "Compact extension: 32 regular or 64 compact slots") +
                                  ", SIZE16/BUS64/COUNT29, all public outputs active")
    (out / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")
    (out / "source_sha256.json").write_text(
        json.dumps(dict(reference_commit=revision, sources=hashes), indent=2) + "\n")


if __name__ == "__main__":
    main()
