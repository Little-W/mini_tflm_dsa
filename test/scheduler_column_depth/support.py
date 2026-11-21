#!/usr/bin/env python3
"""保存列计数器验证使用的参考源码、当前源码和公共依赖。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/control/ps_window_scheduler.sv")
HELPERS = [Path("rtl/common") / name for name in
           ("onehot_check.sv", "parallel_prefix_add.sv", "regfile.v")]
REFERENCE = "4dee27ffec4dc891daf2681379f8b3fd27fd41f2"
PARAMETERS = {"SIZE": 16, "FRAME_COUNT": 16, "MAX_REUSE_TILES": 32}
sys.path.insert(0, str(ROOT / "test"))
from rtl_reference import read_rtl_source


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_inputs(out, reference):
    out.mkdir(parents=True, exist_ok=True)
    source_root = out / "inputs"
    (source_root / "include").mkdir(parents=True, exist_ok=True)
    texts = {
        "reference": read_rtl_source(f"{reference}:{SOURCE}", cwd=ROOT, text=True),
        "current": (ROOT / SOURCE).read_text(),
    }
    paths = {}
    for label, text in texts.items():
        path = source_root / label / SOURCE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        paths[label] = path
    helpers = []
    for name in HELPERS:
        path = source_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / name).read_bytes())
        helpers.append(path)
    manifest = {
        "source": str(SOURCE), "reference_commit": reference,
        "reference_sha256": digest(paths["reference"]),
        "source_sha256": digest(paths["current"]),
        "helper_sha256": {str(name): digest(ROOT / name) for name in HELPERS},
    }
    (out / "inputs.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return source_root, paths, helpers, manifest


def check_sources(manifest):
    if manifest["source_sha256"] != digest(ROOT / SOURCE):
        raise RuntimeError("验证期间调度器源文件发生变化")
    if manifest["helper_sha256"] != {str(name): digest(ROOT / name) for name in HELPERS}:
        raise RuntimeError("验证期间公共模块源文件发生变化")


def increment_body(source):
    first = "    assign active_after_frame[ID_W] = &active_id;"
    last = "    assign active_frame_k = frame_k[active_id];"
    if source.count(first) != 1 or source.count(last) != 1:
        raise RuntimeError("无法唯一提取实际列增量表达式")
    start = source.index(first) + len(first)
    return source[start:source.index(last, start)]
