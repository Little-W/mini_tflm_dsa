#!/usr/bin/env python3
"""证明完整 IA 模块的写入资格、有效字节与其他所有接口和状态。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "cfbbd6bd77b4b0898306689c94ec67d3d71a00af"
PARENT = Path("rtl/npu/loaders/ia_loader.sv")
CACHE = Path("rtl/npu/loaders/ia_loader_cache_mgr.sv")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "test/ia_timing"))
from scripts.rtl.source_files import input_files, with_dependencies
from run_interface import port_declarations

CACHE_PARAMETERS = dict(SIZE=16, DATA_WIDTH=16, BUS_WIDTH=64, DMA_LANES=8,
                        CACHE_BLOCKS=32, RAM_WORD_ADDR_WIDTH=12,
                        p_dma_source_layout=1, p_shared_write_stage=1,
                        p_precomputed_slot_mask=1, p_indexed_slot_rows=1)
IA_PARAMETERS = dict(SIZE=16, BUS_WIDTH=64, CACHE_BLOCKS=32, COUNT_WIDTH=29,
                     ORDERED_JOB=1, RAM_WORD_ADDR_WIDTH=12, p_dma_source_layout=1,
                     p_shared_write_stage=1, p_register_dma_request=1)
PROFILES = {
    "cache_default": ("ia_loader_cache_mgr", dict(CACHE_PARAMETERS, COMPACT_S8=0), True),
    "cache_regular": ("ia_loader_cache_mgr", dict(CACHE_PARAMETERS, COMPACT_S8=0), False),
    "cache_compact": ("ia_loader_cache_mgr", dict(CACHE_PARAMETERS, COMPACT_S8=1), False),
    "cache_four_lanes": ("ia_loader_cache_mgr", dict(CACHE_PARAMETERS, BUS_WIDTH=32,
                                                    DMA_LANES=4, COMPACT_S8=1), False),
    "cache_direct": ("ia_loader_cache_mgr", dict(CACHE_PARAMETERS, COMPACT_S8=1,
                                                p_shared_write_stage=0), False),
    "ia_default": ("ia_loader", dict(IA_PARAMETERS, COMPACT_S8=0), True),
    "ia_regular": ("ia_loader", dict(IA_PARAMETERS, COMPACT_S8=0), False),
    "ia_compact": ("ia_loader", dict(IA_PARAMETERS, COMPACT_S8=1), False),
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def original(relative, revision):
    return subprocess.check_output(["git", "show", revision + ":" + str(relative)],
                                   cwd=ROOT, text=True)


def qualified_interface(source, variant):
    """公开写字节性质，同时保留原模块全部控制、状态和存储实现。"""
    position = source.index("\n);", source.index(") (")) + len("\n);")
    header, body = source[:position], source[position:]
    names = ("ram_port_wr_data", "ram_shared_wr_data")
    for name in names:
        renamed = variant + "_unqualified_" + name
        body = re.sub(r"\b" + name + r"\b", renamed, body)
        # 子模块端口名称保持原定义，连接值使用本证明中的内部数据名称。
        body = re.sub(r"\." + renamed + r"\s*(?=[,)])",
                      "." + name + "(" + renamed + ")", body)
        body = body.replace("." + renamed + "(", "." + name + "(")
    declarations = "\n    logic [127:0] " + variant + "_unqualified_ram_port_wr_data [0:1];\n"
    declarations += "    logic [127:0] " + variant + "_unqualified_ram_shared_wr_data;\n"
    checks = "\n    // 各写字节的资格直接使用真实输出掩码，地址和使能不作修改。\n"
    checks += "    for (genvar byte_index=0;byte_index<16;byte_index++) begin : g_write_byte_property\n"
    for port in range(2):
        value = f"{variant}_unqualified_ram_port_wr_data[{port}][8*byte_index+:8]"
        if port == 1:
            value += f" & {{8{{ram_port_wr_mask[{port}][byte_index]}}}}"
        checks += f"      assign ram_port_wr_data[{port}][8*byte_index+:8] = {value};\n"
    checks += ("      assign ram_shared_wr_data[8*byte_index+:8] = " + variant +
               "_unqualified_ram_shared_wr_data[8*byte_index+:8] & "
               "{8{ram_port_wr_en[1] ? ram_port_wr_mask[1][byte_index] : "
               "ram_port_wr_mask[0][byte_index]}};\n    end\n")
    return header + declarations + body.replace("\nendmodule", checks + "\nendmodule", 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default=REFERENCE)
    parser.add_argument("--profiles", nargs="+", choices=PROFILES, default=list(PROFILES))
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    hashes = {str(path.relative_to(ROOT)): digest(path)
              for path in input_files(with_dependencies([ROOT / PARENT], ROOT), ROOT)}
    source_sets = {}
    for name in args.profiles:
        top, _, preserve_data = PROFILES[name]
        source_sets[name] = {}
        for variant in ("reference", "candidate"):
            directory = out / "sources" / name / variant
            directory.mkdir(parents=True, exist_ok=True)
            paths = []
            relatives = [CACHE] if top == "ia_loader_cache_mgr" else [PARENT, CACHE]
            for relative in relatives:
                text = (original(relative, args.reference) if variant == "reference"
                        else (ROOT / relative).read_text())
                if not preserve_data and relative.stem == top:
                    text = qualified_interface(text, variant)
                path = directory / relative.name
                path.write_text(text)
                paths.append(path)
            source_sets[name][variant] = with_dependencies(paths, ROOT)

    def prove(job):
        name, fpga = job
        top, parameters, preserve_data = PROFILES[name]
        label = name + ("_fpga" if fpga else "_generic")
        flags = (["-DSYNTHESIS=1", "-DXILINX_FPGA=1"] if fpga else
                 ["-USYNTHESIS", "-UXILINX_FPGA"])
        flags += [f"-G{key}={value}" for key, value in parameters.items()]
        commands = []
        for variant in ("reference", "candidate"):
            options = flags + ([] if variant == "reference" else
                               ["-Gp_zero_masked_write_data=" + str(int(preserve_data))])
            commands += ["read_slang --top " + top + " " +
                         shlex.join(options + list(map(str, source_sets[name][variant]))),
                         "setattr -mod -unset keep_hierarchy", "setattr -unset keep_hierarchy",
                         "prep -top " + top + " -flatten", "memory_map", "async2sync", "opt_clean",
                         "rename " + top + " " + variant, "design -stash " + variant]
        blacklist = out / (label + "_unqualified_interfaces.txt")
        blacklist.write_text("u_cache_mgr.ram_port_wr_data\nu_cache_mgr.ram_shared_wr_data\n")
        exclude = " -blacklist " + shlex.quote(str(blacklist)) if not preserve_data and top == "ia_loader" else ""
        commands += ["design -copy-from reference -as reference reference",
                     "design -copy-from candidate -as candidate candidate",
                     "equiv_make" + exclude + " reference candidate proof", "hierarchy -top proof",
                     "equiv_simple -seq 1", "opt_clean", "equiv_induct -seq 4", "equiv_status -assert"]
        script, log = out / (label + ".ys"), out / (label + ".log")
        script.write_text("\n".join(commands) + "\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script],
                           cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=480)
        text = log.read_text()
        match = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", text)
        if not match or int(match[2]) or "Equivalence successfully proven!" not in text:
            raise RuntimeError("IA 写数据性质未完成：" + label)
        record = dict(profile=name, fpga=fpga, parameters=parameters,
                      p_zero_masked_write_data=int(preserve_data), passed=True,
                      all_write_data_compared=preserve_data,
                      all_first_port_data_compared=True,
                      all_enabled_write_bytes_compared=True,
                      all_other_outputs_and_states_compared=True,
                      proven_bits=int(match[1]), script_sha256=digest(script), log_sha256=digest(log))
        print(json.dumps(record), flush=True)
        return record

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        records = list(pool.map(prove, ((name, fpga) for name in args.profiles for fpga in (False, True))))
    if hashes != {name: digest(ROOT / name) for name in hashes}:
        raise RuntimeError("证明期间 RTL 内容发生变化")
    report = dict(passed=True, reference=args.reference, source_sha256=hashes,
                  runner_sha256=digest(__file__), input_value_constraints=None,
                  handshake_constraints=None, profiles=records,
                  proven_bits=sum(row["proven_bits"] for row in records))
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
