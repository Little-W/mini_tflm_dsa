#!/usr/bin/env python3
"""保留实际同步存储输出寄存器，证明完整偏置加载器的逐周期行为。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "87c506be4d2efde77fd94946a3b98bcdd228d235"
spec = importlib.util.spec_from_file_location(
    "bias_shared_proof", ROOT / "test/bias_shared_arithmetic/run_formal.py")
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)


def abstract_contents(source, filename):
    """存储字数据共用任意输入，实际读资格和输出保持寄存器保持原样。"""
    if filename == "bias_loader.sv":
        source = shared.observe_storage(source)
        return source.replace("u_buffer.storage_i_rd_en", "u_buffer.u_storage.read_accept[0]")
    if filename == "bias_loader_buffer.sv":
        marker = "    input  wire logic clk,"
        if source.count(marker) != 1:
            raise RuntimeError("缓冲区输入定义不符合预期")
        source = source.replace(marker, "    input logic [63:0] i_formal_read_data,\n" + marker)
        marker = ".o_rd_data(storage_o_rd_data)"
        if source.count(marker) != 1:
            raise RuntimeError("同步存储实例不符合预期")
        return source.replace(marker, marker + ", .i_formal_read_data(i_formal_read_data)")
    if filename == "regfile.v":
        marker = "    input  wire logic clk,"
        if source.count(marker) != 1:
            raise RuntimeError("存储器输入定义不符合预期")
        source = source.replace(marker,
            "    input logic [p_data_width-1:0] i_formal_read_data,\n" + marker)
        marker = "mem[i_rd_addr[port_index]]"
        if source.count(marker) != 2:
            raise RuntimeError("同步与异步数据读取定义不符合预期")
        return source.replace(marker, "i_formal_read_data")
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference", default=REFERENCE)
    parser.add_argument("--profiles", type=int, nargs="*", default=list(range(len(shared.PROFILES))))
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
            target = out / "sources" / label / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            model = out / "models" / label / relative.name
            model.parent.mkdir(parents=True, exist_ok=True)
            model.write_text(abstract_contents(data.decode(), relative.name))
            snapshots[label].append(model)
    records = []
    for index in args.profiles:
        parameters = shared.PROFILES[index]
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
                "write_rtlil " + shlex.quote(str(folder / (label + ".il"))),
            ]
            shared.run_worker(folder, label, commands)
            module = json.loads((folder / (label + "_state.json")).read_text())["modules"][label]
            names, states[label] = shared.combinational_names(module)
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
        proof = shared.run_worker(folder, "proof", commands)
        match = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven",
                          (folder / "proof.log").read_text())
        if match is None or int(match[2]):
            raise RuntimeError(str(folder / "proof.log"))
        record = dict(parameters=parameters, passed=True, equivalent_bits=int(match[1]),
                      state_signal_names=states, unbounded_equivalence=True, proof=proof)
        records.append(record)
        print(json.dumps({key: record[key] for key in ("parameters", "passed", "equivalent_bits")}),
              flush=True)
    if hashes["current"] != {str(path.relative_to(root)): shared.digest(path) for path in files}:
        raise RuntimeError("验证期间 RTL 源文件发生变化")
    report = dict(passed=True, reference_commit=revision, external_input_assumptions=[],
                  memory_contents="每次可能读取的数据为两侧共用的任意64位输入",
                  storage_control="保留实际读写资格以及同步输出寄存器的使能和保持行为",
                  compared_storage_ports="实际读取资格、完整读写地址、写入数据、字节掩码及写入使能",
                  internal_correspondence="仅真实寄存器输出，组合信号全部排除",
                  source_sha256=hashes, profiles=records, runner_sha256=shared.digest(Path(__file__)))
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
