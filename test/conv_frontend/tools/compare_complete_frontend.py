#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""逐周期比较完整前端层次，参考实例使用独立的全部 RTL 模块。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys

from compare_frontend import compare_bench, widen_memory


ROOT = Path(__file__).resolve().parents[3]
BENCH_ROOT = ROOT / "test/conv_frontend"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command: list[str], log: Path, timeout: int = 1200) -> None:
    with log.open("w") as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=timeout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-source-root", type=Path, required=True)
    parser.add_argument("--candidate-source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--size", type=int, default=16)
    parser.add_argument("--slot-width", type=int, default=5)
    parser.add_argument("--lanes", type=int, default=4)
    parser.add_argument("--bus-width", type=int, choices=(32, 64), default=64)
    parser.add_argument("--cache-sets", type=int, default=128)
    parser.add_argument("--line-bytes", type=int, default=16)
    parser.add_argument("--register-descriptor", type=int, choices=(0, 1), default=0)
    parser.add_argument("--cache-response-depth", type=int, default=1)
    parser.add_argument("--windowed", action="store_true")
    parser.add_argument("--fpga", action="store_true")
    parser.add_argument("--synthesis", action="store_true")
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    if args.slot_width < 3:
        parser.error("--slot-width must accommodate the eight numerical test slots")
    root = args.candidate_source_root.resolve()
    reference_root = args.reference_source_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    # 两套设计各自解析依赖，参考层次中的模块和包统一改名，避免共享候选子模块。
    selected = [root / name for name in (
        "rtl/npu/conv/conv_im2col_pkg.sv",
        "rtl/npu/dma/cache/conv_sdp_ram.sv",
        "rtl/npu/dma/cache/conv_next_use_predictor.sv",
        "rtl/npu/conv/conv_axi_span_reader.sv",
        "rtl/npu/dma/cache/conv_read_cache.sv",
        "rtl/npu/conv/conv_im2col_frontend.sv",
        "rtl/npu/conv/conv_ia_write_adapter.sv",
        "rtl/npu/conv/conv_ia_tile_path.sv",
    )]
    candidate_files = runpy.run_path(str(root / "test/monitors/sources.py"))["with_observers"](selected)
    reference_files = runpy.run_path(str(reference_root / "test/monitors/sources.py"))["with_observers"](
        [reference_root / path.relative_to(root) for path in selected])
    reference_text = {path: path.read_text() for path in reference_files}
    names = set()
    for text in reference_text.values():
        stripped = re.sub(r"//[^\n]*|/\*.*?\*/", "", text, flags=re.S)
        names.update(re.findall(r"\b(?:module|package)\s+(\w+)", stripped))
    pattern = re.compile(r"\b(?:" + "|".join(sorted(map(re.escape, names), key=len, reverse=True)) + r")\b")
    transformed = []
    included_files = set()
    for path, text in reference_text.items():
        target = out / "reference" / path.relative_to(reference_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        def include_source(match: re.Match) -> str:
            include = reference_root / "include" / match.group(1)
            if not include.is_file():
                return match.group()
            included_files.add(include)
            return include.read_text()
        text = re.sub(r'`include\s+"([^"]+)"', include_source, text)
        target.write_text(pattern.sub(lambda match: "reference_" + match.group(), text))
        transformed.append(target)

    for path in candidate_files:
        for include_name in re.findall(r'`include\s+"([^"]+)"', path.read_text()):
            include = root / "include" / include_name
            if include.is_file():
                included_files.add(include)
    original_hashes = {str(path): digest(path)
                       for path in [*candidate_files, *reference_files, *included_files]}
    sources = [*candidate_files, *transformed]
    if args.synthesis:
        for index, path in enumerate(sources):
            if "test/monitors/" in str(path):
                target = out / "synthesis_observers" / str(index) / path.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("`undef SYNTHESIS\n" + path.read_text() + "\n`define SYNTHESIS 1\n")
                sources[index] = target

    test_path = out / "tb_conv_im2col_frontend.sv"
    content = widen_memory((BENCH_ROOT / "tests/tb_conv_im2col_frontend.sv").read_text())
    content = content.replace("parameter int NARROW_MODE=0;", "parameter int NARROW_MODE=0, SLOT_W=3;")
    content = content.replace("logic [2:0] tile_slot", "logic [SLOT_W-1:0] tile_slot")
    content = content.replace("logic [2:0] wr_slot", "logic [SLOT_W-1:0] wr_slot")
    content = content.replace(".SLOT_W(3)", ".SLOT_W(SLOT_W)")
    content = content.replace("tile_slot=3'(v[3])", "tile_slot=SLOT_W'(v[3])")
    test_path.write_text(compare_bench(content, 1, args.register_descriptor, args.cache_response_depth))
    source_manifest = {str(path): digest(path) for path in [*sources, test_path]}
    vectors = out / "vectors.txt"
    run([sys.executable, str(BENCH_ROOT / "tests/gen_rtl_vectors.py"), "--size", str(args.size),
         "--out", str(vectors)], out / "vectors.log")
    command = [shutil.which("verilator") or "verilator", "--binary", "--timing", "--assert",
               "-I" + str(root / "include"),
               "-DNPU_SIM_ASSERT", "-DCONV_ASSERT", "-Wall", "-Wno-fatal",
               *(["-DXILINX_FPGA=1"] if args.fpga else []),
               *(["-DSYNTHESIS=1"] if args.synthesis else []),
               "--top-module", "tb_conv_im2col_frontend", f"-GSIZE={args.size}",
               f"-GSLOT_W={args.slot_width}",
               f"-GBUS_WIDTH={args.bus_width}", f"-GLANES={args.lanes}",
               f"-GLINE_BYTES={args.line_bytes}",
               f"-GCACHE_SETS={args.cache_sets}", f"-GWINDOWED=1'b{int(args.windowed)}",
               f"-GPREFETCH=1'b{int(args.windowed)}", "-GNARROW_MODE=2",
               "--Mdir", str(out / "obj"), "-j", str(args.jobs),
               "--output-groups", "0", "--output-split", "12000", "-CFLAGS", "-std=c++20 -O1",
               "-MAKEFLAGS", "OPT_FAST=-O1 OPT_SLOW=-O0 VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E",
               *map(str, sources), str(test_path)]
    run(command, out / "build.log")
    warnings = [line for line in (out / "build.log").read_text().splitlines() if line.startswith("%Warning")]
    functional_warnings = [line for line in warnings if line.startswith((
        "%Warning-MULTIDRIVEN", "%Warning-LATCH", "%Warning-PINMISSING", "%Warning-IMPLICIT"))]
    if functional_warnings:
        raise RuntimeError("RTL diagnostics: " + repr(functional_warnings))
    binary = out / "obj/Vtb_conv_im2col_frontend"
    run([str(binary), "+VECTORS=" + str(vectors)], out / "run.log", timeout=240)
    summary = [line for line in (out / "run.log").read_text().splitlines()
               if line.startswith(("RTL_FRONTEND_PASS", "FRONTEND_COMPARE_PASS"))]
    if len(summary) != 2:
        raise RuntimeError("Incomplete frontend comparison")
    if any(digest(Path(path)) != value for path, value in original_hashes.items()):
        raise RuntimeError("RTL source changed during comparison")
    result = {"passed": True, "scope": "Complete independent RTL hierarchies; all public outputs on every cycle",
              "reference_source_root": str(reference_root), "candidate_source_root": str(root),
              "parameters": {key: value for key, value in vars(args).items() if not isinstance(value, Path)},
              "source_sha256": original_hashes, "compiled_source_sha256": source_manifest,
              "renamed_reference_definitions": sorted(names), "warnings": warnings,
              "summary": summary, "binary_sha256": digest(binary)}
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"passed": True, "summary": summary, "out": str(out)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
