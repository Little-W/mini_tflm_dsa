#!/usr/bin/env python3
"""保存列计数器验证使用的参考源码、当前源码和公共依赖。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/control/ps_window_scheduler.sv")
HELPERS = [Path("rtl/common") / name for name in
           ("onehot_check.sv", "parallel_prefix_add.sv", "regfile.v", "unsigned_compare.sv")]
REFERENCE = str(ROOT / "test/scheduler_column_depth/reference_scheduler.sv")
PARAMETERS = {"SIZE": 16, "FRAME_COUNT": 16, "MAX_REUSE_TILES": 32}
sys.path.insert(0, str(ROOT / "test"))
from rtl_reference import read_rtl_source
sys.path.insert(0, str(ROOT / "scripts/rtl"))
from source_files import with_dependencies


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def module_hashes(text):
    """记录组合源码内各模块的内容，包含参考文件自带的子模块。"""
    matches = list(re.finditer(r"\bmodule\s+(\w+)\b[\s\S]*?\bendmodule\b", text))
    names = [match[1] for match in matches]
    if len(names) != len(set(names)):
        raise RuntimeError("验证输入包含重复模块定义")
    return {match[1]: hashlib.sha256(match[0].encode()).hexdigest() for match in matches}


def proof_state_aliases(text):
    """为形式模型的数组元素提供对应名称，寄存器及连接保持原样。"""
    aliases = {}
    for array, names in {
        "prediction_depth_q": ("prediction_q_s0", "prediction_q_direct_s1", "prediction_q_s1"),
        "prediction_column_q": ("prediction_column_s0", "prediction_column_direct_s1", "prediction_column_s1"),
    }.items():
        if re.search(r"\blogic\s*\[31:0\]\s*" + array + r"\s*\[3\]", text):
            aliases.update({f"{array}[{index}]": name for index, name in enumerate(names)})
    if re.search(r"\blogic\s+prediction_reads_frame_q\s*\[2\]", text):
        aliases.update({
            "prediction_reads_frame_q[0]": "prediction_reads_frame_s0",
            "prediction_reads_frame_q[1]": "prediction_reads_frame_q",
        })
    return aliases


def prepare_inputs(out, reference, candidate=None):
    out.mkdir(parents=True, exist_ok=True)
    source_root = out / "inputs"
    (source_root / "include").mkdir(parents=True, exist_ok=True)
    reference_path = Path(reference)
    candidate_path = (Path(candidate) if candidate is not None else ROOT / SOURCE).resolve()
    texts = {
        "reference": reference_path.read_text() if reference_path.is_file() else
            read_rtl_source(f"{reference}:{SOURCE}", cwd=ROOT, text=True),
        "current": candidate_path.read_text(),
    }
    helpers = []
    for name in HELPERS:
        path = source_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / name).read_bytes())
        helpers.append(path)
    paths, dependencies, prepared_hashes, module_sha256 = {}, {}, {}, {}
    for label, text in texts.items():
        path = source_root / label / SOURCE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        # 每侧分别解析实际引用。参考文件已有的定义优先保留，避免再次加入同名模块。
        supplied = [path] + helpers
        original = reference_path if label == "reference" else candidate_path
        defined = set(module_hashes(text))
        for name in ("ps_scheduler_any", "ps_scheduler_priority"):
            sibling = original.with_name(name + ".sv")
            if name not in defined and re.search(r"\b" + name + r"\b", text) and sibling.is_file():
                supplied.append(sibling.resolve())
        resolved = with_dependencies(supplied, ROOT)
        extra = [item for item in resolved if item not in [path] + helpers]
        combined = "\n".join([text] + [item.read_text() for item in extra])
        module_sha256[label] = module_hashes(combined)
        module_hashes(combined + "\n" + "\n".join(item.read_text() for item in helpers))
        path.write_text(combined)
        paths[label] = path
        prepared_hashes[label] = digest(path)
        dependencies[label] = {str(item): digest(item) for item in extra}
    manifest = {
        "source": str(SOURCE),
        "reference_commit": None if reference_path.is_file() else reference,
        "reference_file": str(reference_path.resolve()) if reference_path.is_file() else None,
        "source_path": str(candidate_path),
        "reference_sha256": hashlib.sha256(texts["reference"].encode()).hexdigest(),
        "source_sha256": hashlib.sha256(texts["current"].encode()).hexdigest(),
        "helper_sha256": {str(name): digest(ROOT / name) for name in HELPERS},
        "dependency_sha256": dependencies,
        "prepared_source_sha256": prepared_hashes,
        "module_sha256": module_sha256,
    }
    (out / "inputs.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return source_root, paths, helpers, manifest


def check_sources(manifest):
    if manifest["source_sha256"] != digest(Path(manifest.get("source_path", ROOT / SOURCE))):
        raise RuntimeError("验证期间调度器源文件发生变化")
    if manifest["helper_sha256"] != {name: digest(ROOT / name) for name in manifest["helper_sha256"]}:
        raise RuntimeError("验证期间公共模块源文件发生变化")
    for dependencies in manifest.get("dependency_sha256", {}).values():
        if any(digest(Path(path)) != expected for path, expected in dependencies.items()):
            raise RuntimeError("验证期间调度器子模块源文件发生变化")


def increment_body(source):
    first = "    assign active_after_frame[ID_W] = &active_id;"
    last = "    assign active_frame_k = frame_k[active_id];"
    if source.count(first) != 1 or source.count(last) != 1:
        raise RuntimeError("无法唯一提取实际列增量表达式")
    start = source.index(first) + len(first)
    return source[start:source.index(last, start)]
