#!/usr/bin/env python3
"""证明完整偏置加载器的状态、公开输出和同步存储端口逐周期一致。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "17dda6a11cd55ea470712335f2b5cfcfca4b4bd4"
sys.path.insert(0, str(ROOT / "test/bias_read_depth"))
from common import abstract_storage, abstract_wrapper

PROFILES = (
    dict(SIZE=4, BUS_WIDTH=32, REG_WIDTH=8, COUNT_WIDTH=1, GROUP_BLOCKS_MAX=1),
    dict(SIZE=8, BUS_WIDTH=32, REG_WIDTH=16, COUNT_WIDTH=8, GROUP_BLOCKS_MAX=3),
    dict(SIZE=16, BUS_WIDTH=32, REG_WIDTH=32, COUNT_WIDTH=12, GROUP_BLOCKS_MAX=4),
    dict(SIZE=16, BUS_WIDTH=64, REG_WIDTH=32, COUNT_WIDTH=29, GROUP_BLOCKS_MAX=16),
    dict(SIZE=16, BUS_WIDTH=64, REG_WIDTH=32, COUNT_WIDTH=32, GROUP_BLOCKS_MAX=32),
    dict(SIZE=16, BUS_WIDTH=128, REG_WIDTH=32, COUNT_WIDTH=29, GROUP_BLOCKS_MAX=16),
    dict(SIZE=16, BUS_WIDTH=64, REG_WIDTH=64, COUNT_WIDTH=64, GROUP_BLOCKS_MAX=16),
    dict(SIZE=16, BUS_WIDTH=64, REG_WIDTH=16, COUNT_WIDTH=29, GROUP_BLOCKS_MAX=16),
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def observe_storage(source):
    """存储返回共用任意输入，并将全部存储驱动信号加入公开比较端口。"""
    source = abstract_wrapper(source)
    boundary = source.index("\n\t);", source.index(") ("))
    source = source[:boundary] + ",\n    output logic [137:0] formal_storage" + source[boundary:]
    assignments = """
    assign formal_storage = {
        u_buffer.storage_i_wr_en, u_buffer.storage_i_rd_en,
        32'(u_buffer.storage_i_wr_addr), 32'(u_buffer.storage_i_rd_addr),
        u_buffer.storage_i_wr_data, u_buffer.storage_i_wr_mask};
"""
    return source.replace("\nendmodule", assignments + "\nendmodule", 1)


def run_worker(folder, name, commands):
    script, log = folder / (name + ".ys"), folder / (name + ".log")
    script.write_text("\n".join(commands) + "\n")
    with log.open("w") as stream:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
            stdout=stream, stderr=subprocess.STDOUT, timeout=900)
    if result.returncode:
        raise RuntimeError(str(log))
    return dict(script_sha256=digest(script), log_sha256=digest(log))


def combinational_names(module):
    """仅允许真实寄存器输出及模块公开端口建立内部状态对应。"""
    registered = set()
    for cell in module["cells"].values():
        if re.fullmatch(r"\$(?:[a-z]*dff[a-z]*|[a-z]*latch[a-z]*|ff)", cell["type"]):
            registered.update(bit for bit in cell["connections"].get("Q", [])
                              if isinstance(bit, int))
    excluded = set(module["cells"])
    retained = []
    for name, wire in module["netnames"].items():
        if name in module["ports"]:
            continue
        bits = {bit for bit in wire["bits"] if isinstance(bit, int)}
        if bits and bits <= registered:
            retained.append(name)
        else:
            excluded.add(name)
    return excluded, retained


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
    resolve = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]
    files = resolve([root / "rtl/npu/loaders/bias_loader.sv"], root)
    hashes, snapshots = {}, {}
    for label in ("reference", "current"):
        hashes[label], snapshots[label] = {}, []
        for original in files:
            relative = original.relative_to(root)
            data = (subprocess.check_output(["git", "show", f"{revision}:{relative}"], cwd=ROOT)
                    if label == "reference" else original.read_bytes())
            hashes[label][str(relative)] = hashlib.sha256(data).hexdigest()
            path = out / "sources" / label / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            model = out / "models" / label / relative.name
            model.parent.mkdir(parents=True, exist_ok=True)
            text = data.decode()
            if relative.name == "bias_loader.sv":
                text = observe_storage(text)
            elif relative.name == "bias_loader_buffer.sv":
                text = abstract_storage(text)
            model.write_text(text)
            snapshots[label].append(model)
    records = []
    for index, parameters in enumerate(PROFILES):
        folder = out / f"profile_{index}"
        folder.mkdir(exist_ok=True)
        excluded, states = set(), {}
        for label in ("reference", "current"):
            options = " ".join(f"-G{name}={value}" for name, value in parameters.items())
            commands = [
                f"read_slang --top bias_loader -DSYNTHESIS=1 -DXILINX_FPGA=1 {options} " +
                shlex.join(map(str, snapshots[label])),
                "setattr -mod -unset keep_hierarchy", "setattr -unset keep_hierarchy",
                "prep -top bias_loader -flatten", "memory_map", "opt -full",
                f"rename -top {label}",
                "write_json " + shlex.quote(str(folder / (label + "_state.json"))),
                "async2sync", "opt -full", "check -assert",
                "write_json " + shlex.quote(str(folder / (label + ".json"))),
                "write_rtlil " + shlex.quote(str(folder / (label + ".il"))),
            ]
            run_worker(folder, label, commands)
            module = json.loads((folder / (label + "_state.json")).read_text())["modules"][label]
            names, states[label] = combinational_names(module)
            excluded.update(names)
        blacklist = folder / "combinational_names.txt"
        blacklist.write_text("\n".join(sorted(excluded)) + "\n")
        commands = [
            "read_rtlil " + shlex.quote(str(folder / "reference.il")),
            "read_rtlil " + shlex.quote(str(folder / "current.il")),
            "equiv_make -blacklist " + shlex.quote(str(blacklist)) + " reference current equivalent",
            "hierarchy -top equivalent", "equiv_simple -short -seq 1", "opt_clean",
            "equiv_induct -seq 8", "equiv_status -assert",
        ]
        proof = run_worker(folder, "proof", commands)
        match = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven",
                          (folder / "proof.log").read_text())
        if match is None or int(match[2]):
            raise RuntimeError(str(folder / "proof.log"))
        record = dict(parameters=parameters, passed=True, equivalent_bits=int(match[1]),
                      state_signal_names=states, unbounded_equivalence=True, proof=proof)
        records.append(record)
        print(json.dumps({key: record[key] for key in ("parameters", "passed", "equivalent_bits")}),
              flush=True)
    unchanged = hashes["current"] == {
        str(path.relative_to(root)): digest(path) for path in files}
    if not unchanged:
        raise RuntimeError("验证期间 RTL 源文件发生变化")
    report = dict(passed=True, reference_commit=revision, external_input_assumptions=[],
                  storage_read_data="两侧每周期共用任意 64 位输入",
                  compared_storage_ports="完整读写地址、写入数据、字节掩码及读写使能",
                  internal_correspondence="仅真实寄存器输出，组合信号全部排除",
                  source_sha256=hashes, sources_unchanged=unchanged, profiles=records)
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
