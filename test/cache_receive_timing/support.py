#!/usr/bin/env python3
"""保存窗口缓存验证使用的源码与依赖。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/dma/cache/conv_read_cache.sv")
REFERENCE = "dde5e7c9836a71f0292d7c69040f8635840e6bad"
PARAMETERS = {"SETS": 128, "WAYS": 2, "LINE_BYTES": 16, "BUS_WIDTH": 64,
              "READ_WIDTH": 32, "p_defer_retire_shift": 1}
DEPENDENCIES = [Path(name) for name in (
    "rtl/npu/dma/cache/conv_sdp_ram.sv", "rtl/npu/conv/conv_axi_span_reader.sv",
    "rtl/npu/conv/conv_axi_read_guard.sv")]
sys.path.insert(0, str(ROOT / "test"))
from rtl_reference import read_rtl_source


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_inputs(out, reference, candidate=None):
    out.mkdir(parents=True, exist_ok=True)
    source_root = out / "inputs"
    (source_root / "include").mkdir(parents=True, exist_ok=True)
    candidate = (candidate or ROOT / SOURCE).resolve()
    reference_file = Path(reference)
    texts = {"reference": reference_file.read_text() if reference_file.is_file() else
             read_rtl_source(f"{reference}:{SOURCE}", cwd=ROOT, text=True),
             "current": candidate.read_text()}
    paths = {}
    for label, text in texts.items():
        path = source_root / label / SOURCE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        paths[label] = path
    dependencies = DEPENDENCIES + [path.relative_to(ROOT)
        for path in sorted((ROOT / "rtl/common").rglob("*")) if path.suffix in (".v", ".sv")]
    helpers = []
    for name in dependencies:
        path = source_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / name).read_bytes())
        helpers.append(path)
    manifest = {"source": str(SOURCE), "candidate_input": str(candidate),
        "reference_commit": None if reference_file.is_file() else reference,
        "reference_file": str(reference_file.resolve()) if reference_file.is_file() else None,
        "reference_sha256": digest(paths["reference"]),
        "source_sha256": digest(paths["current"]),
        "helper_sha256": {str(name): digest(source_root / name) for name in dependencies}}
    (out / "inputs.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return source_root, paths, helpers, manifest


def check_sources(manifest):
    if digest(Path(manifest["candidate_input"])) != manifest["source_sha256"]:
        raise RuntimeError("验证期间窗口缓存源码发生变化")
    for name, expected in manifest["helper_sha256"].items():
        if digest(ROOT / name) != expected:
            raise RuntimeError("验证期间依赖模块发生变化: " + name)
