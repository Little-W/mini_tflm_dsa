#!/usr/bin/env python3
"""固定完整偏置加载器及依赖，生成当前 SoC 参数的前后综合配置。"""
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
REFERENCE = "17dda6a11cd55ea470712335f2b5cfcfca4b4bd4"
PARAMETERS = dict(SIZE=16, DATA_WIDTH=32, BUS_WIDTH=64, REG_WIDTH=32,
                  COUNT_WIDTH=29, GROUP_BLOCKS_MAX=16)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default=REFERENCE)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
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
        for label, source_root in (("reference", original), ("current", root)):
            common = sorted(path for path in (source_root / "rtl/common").rglob("*")
                            if path.suffix in (".sv", ".v"))
            files = resolve([source_root / "rtl/npu/loaders/bias_loader.sv"] + common, source_root)
            hashes[label] = {}
            names = []
            for path in files:
                relative = path.relative_to(source_root)
                target = out / label / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                data = path.read_bytes()
                target.write_bytes(data)
                hashes[label][str(relative)] = hashlib.sha256(data).hexdigest()
                names.append(str(relative))
            cases[label] = dict(top="bias_loader", sources=names, parameters=PARAMETERS,
                options=["-DSYNTHESIS=1", "-DXILINX_FPGA=1"] +
                        [f"-G{name}={value}" for name, value in PARAMETERS.items()],
                configuration="完整偏置加载器，SIZE16、DATA32、BUS64、REG32、COUNT29、GROUP16")
    (out / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n")
    (out / "source_sha256.json").write_text(
        json.dumps(dict(reference_commit=revision, sources=hashes), indent=2) + "\n")
    for label in cases:
        print(f"{label}: --source-root {out / label} --case-config {out / 'cases.json'} --cases {label}")


if __name__ == "__main__":
    main()
