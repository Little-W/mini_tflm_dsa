#!/usr/bin/env python3
"""按完整模块分批执行当前 Xilinx ABC9 流程，并保存完整设计检查点。"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sys

PREFIX = ["opt_expr -mux_undef -noclkinv",
          "read_verilog -icells -lib -specify +/xilinx/abc9_model.v"]
SUFFIX = ["clean", "xilinx_srl -fixed -minlen 3",
          "techmap -map +/xilinx/lut_map.v -map +/xilinx/cells_map.v -D LUT_WIDTH=6",
          "xilinx_dffopt", "opt_lut_ins -tech xilinx"]
LIBRARIES = ["read_verilog -lib -specify -overwrite +/xilinx/cells_sim.v",
             "read_verilog -lib -overwrite +/xilinx/cells_xtra.v"]
LEAF_TYPES = {"$_NOT_", "$_AND_", "$_NAND_", "$_OR_", "$_NOR_", "$_XOR_",
              "$_XNOR_", "$_ANDNOT_", "$_ORNOT_", "$_MUX_", "$_NMUX_",
              "$_AOI3_", "$_OAI3_", "$_AOI4_", "$_OAI4_", "$buf"}


def digest(path, *, compressed=False):
    checksum = hashlib.sha256()
    opener = gzip.open if compressed else open
    with opener(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def write_json(path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def interfaces(design, names):
    result = {}
    for name in names:
        module = design.module(name)
        if module is None or module.get_blackbox_attribute() or module.get_bool_attribute("\\whitebox"):
            raise RuntimeError("完整设计中的模块缺失或成为不透明模块：" + name)
        result[name] = sorted((str(wire.name), wire.width, wire.port_input, wire.port_output,
                              wire.port_id, wire.start_offset, wire.upto, wire.is_signed)
                              for wire in module.wires_.values() if wire.port_input or wire.port_output)
    return result


def combinational_leaf(module):
    """只选择没有状态、子模块、未知常量和双向端口的小型组合模块。"""
    from pyosys import libyosys as yosys
    if any(character.isspace() for character in str(module.name)):
        return False
    if module.has_processes() or module.has_memories() or module.cells_size() > 512:
        return False
    if any(wire.port_input and wire.port_output for wire in module.wires_.values()):
        return False
    signals = [signal for pair in module.connections() for signal in pair]
    for cell in module.cells_.values():
        if str(cell.type) not in LEAF_TYPES:
            return False
        signals.extend(cell.connections_.values())
    return all(bit.wire is not None or bit.data in (yosys.State.S0, yosys.State.S1)
               for signal in signals for bit in signal.bits())


def select_modules(design, names):
    from pyosys import libyosys as yosys
    yosys.run_pass("select -clear", design)
    yosys.run_pass("setattr -mod -unset npu_abc9_leaf_module", design)
    for name in names:
        design.module(name).set_bool_attribute("\\npu_abc9_leaf_module", True)
    yosys.run_pass("select A:npu_abc9_leaf_module", design)
    selected = [str(module.name) for module in design.selected_unboxed_whole_modules_warn()]
    if len(selected) != len(names) or set(selected) != set(names):
        raise RuntimeError("独立组合模块的完整选择与清单不同")


def leaf_signature(module):
    """按端口和布尔运算结构识别相同组合函数；所有复用结果仍逐模块证明。"""
    from pyosys import libyosys as yosys
    parent = {}

    def bit_key(bit):
        if bit.wire is not None:
            return (1, str(bit.wire.name), bit.offset)
        if bit.data == yosys.State.S0:
            return (0, 0)
        if bit.data == yosys.State.S1:
            return (0, 1)
        raise RuntimeError("组合函数签名包含未定义常量")

    def root(key):
        parent.setdefault(key, key)
        if parent[key] != key:
            parent[key] = root(parent[key])
        return parent[key]

    connections = list(module.connections())
    for cell in module.cells_.values():
        if str(cell.type) == "$buf":
            lhs, rhs = cell.connections_["\\Y"], cell.connections_["\\A"]
            if lhs.size() != rhs.size():
                raise RuntimeError("组合缓冲单元的输入和输出宽度不同")
            connections.append((lhs, rhs))
    for lhs, rhs in connections:
        for a, b in zip(lhs.bits(), rhs.bits()):
            a, b = root(bit_key(a)), root(bit_key(b))
            parent[max(a, b)] = min(a, b)
    inputs, drivers, cache, active = {}, {}, {}, set()
    ports = sorted((wire for wire in module.wires_.values() if wire.port_id),
                   key=lambda wire: wire.port_id)
    for wire in ports:
        if wire.port_input:
            for index in range(wire.width):
                inputs.setdefault(root((1, str(wire.name), index)), []).append((str(wire.name), index))
    for cell in module.cells_.values():
        if str(cell.type) == "$buf":
            continue
        for bit in cell.connections_["\\Y"].bits():
            key = root(bit_key(bit))
            if key in drivers:
                raise RuntimeError("组合模块包含多个驱动")
            drivers[key] = cell

    def expression(key):
        key = root(key)
        if key in cache:
            return cache[key]
        if key in active:
            raise RuntimeError("组合模块包含组合环")
        active.add(key)
        if key[0] == 0:
            value = ("constant", key[1])
        elif key in inputs:
            value = ("input", sorted(inputs[key]))
        elif key in drivers:
            cell = drivers[key]
            arguments = [(str(port), [expression(bit_key(bit)) for bit in signal.bits()])
                         for port, signal in cell.connections_.items() if str(port) != "\\Y"]
            value = (str(cell.type), sorted(arguments))
        else:
            raise RuntimeError("组合模块包含未驱动信号")
        active.remove(key)
        cache[key] = hashlib.sha256(repr(value).encode()).hexdigest()
        return cache[key]

    metadata = [(str(wire.name), wire.width, wire.port_input, wire.port_output,
                 wire.port_id, wire.start_offset, wire.upto, wire.is_signed) for wire in ports]
    outputs = [(str(wire.name), [expression((1, str(wire.name), index))
                                for index in range(wire.width)]) for wire in ports if wire.port_output]
    return hashlib.sha256(repr((metadata, outputs)).encode()).hexdigest()


def map_leaves(design, names, specification, command):
    """在独立设计中使用相同 ABC9 命令映射叶模块，并逐模块证明全部输出等价。"""
    from pyosys import libyosys as yosys
    before_path = specification.with_suffix(".leaves_before.il")
    after_path = specification.with_suffix(".leaves_after.il")
    expected = interfaces(design, names)
    original_attributes = {name: dict(design.module(name).attributes.items()) for name in names}
    original_port_attributes = {
        name: {str(wire.name): dict(wire.attributes.items())
               for wire in design.module(name).wires_.values() if wire.port_id} for name in names}
    representatives, signatures, copies = [], {}, {}
    for name in names:
        signature = leaf_signature(design.module(name))
        if signature in signatures:
            copies[name] = signatures[signature]
        else:
            representatives.append(name)
            signatures[signature] = name
    select_modules(design, names)
    yosys.run_pass("write_rtlil -selected " + shlex.quote(str(before_path)), design)
    isolated = yosys.Design()
    run = lambda value: yosys.run_pass(value, isolated)
    run("read_rtlil " + shlex.quote(str(before_path)))
    for value in LIBRARIES:
        run(value)
    run("read_verilog -icells -lib -specify -overwrite +/xilinx/abc9_model.v")
    select_modules(isolated, names)
    run("check -assert")
    select_modules(isolated, representatives)
    run(command)
    if copies:
        select_modules(isolated, list(copies))
        run("delete")
        for name, representative in copies.items():
            duplicate = isolated.module(representative).clone()
            duplicate.name = name
            isolated.add(duplicate)
    for name in names:
        module = isolated.module(name)
        for key in list(module.attributes.keys()):
            del module.attributes[key]
        for key, value in original_attributes[name].items():
            module.attributes[key] = value
        for port, attributes in original_port_attributes[name].items():
            wire = module.wire(port)
            for key in list(wire.attributes.keys()):
                del wire.attributes[key]
            for key, value in attributes.items():
                wire.attributes[key] = value
    if interfaces(isolated, names) != expected:
        raise RuntimeError("独立组合模块的端口发生变化")
    select_modules(isolated, names)
    run("write_rtlil -selected " + shlex.quote(str(after_path)))
    del run, isolated

    proof = yosys.Design()
    prove = lambda value: yosys.run_pass(value, proof)
    prove("read_rtlil " + shlex.quote(str(before_path)))
    for index, name in enumerate(names):
        prove("rename " + name + f" npu_leaf_before_{index}")
    prove("read_rtlil " + shlex.quote(str(after_path)))
    prove("setattr -mod -unset keep_hierarchy")
    prove("setattr -unset keep_hierarchy")
    for index, name in enumerate(names):
        prove(f"miter -equiv -flatten npu_leaf_before_{index} " + name +
              f" npu_leaf_proof_{index}")
        prove(f"sat -set-def-inputs -prove trigger 0 -verify npu_leaf_proof_{index}")
    del prove, proof

    yosys.run_pass("select -clear", design)
    yosys.run_pass("read_rtlil -overwrite " + shlex.quote(str(after_path)), design)
    yosys.run_pass("setattr -mod -unset npu_abc9_leaf_module", design)
    if interfaces(design, names) != expected:
        raise RuntimeError("合并组合模块后端口发生变化")
    before_path.unlink()
    after_path.unlink()
    print("\nABC9_LEAF_PROOFS " + str(len(names)), flush=True)
    print("\nABC9_LEAF_FUNCTIONS " + str(len(representatives)), flush=True)


def worker(specification):
    from pyosys import libyosys as yosys
    print("ABC9_WORKER_PID", os.getpid(), flush=True)
    spec = json.loads(specification.read_text())
    design = yosys.Design()
    run = lambda command: yosys.run_pass(command, design)
    run("read_rtlil " + shlex.quote(spec["input"]))
    # 完整设计使用直接连接保存，每次恢复后检查所有模块的驱动关系。
    run("bufnorm -conn")
    run("check -assert")
    if spec["mode"] == "prepare":
        for command in LIBRARIES + spec["prefix"]:
            run(command)
        modules = list(design.selected_unboxed_whole_modules_warn())
        names = [str(module.name) for module in modules]
        inventory = {"modules": names, "interfaces": interfaces(design, names),
                     "module_cells": {str(module.name): module.cells_size() for module in modules}}
        write_json(Path(spec["inventory"]), inventory)
    else:
        # RTLIL 保存完整电路；参数化库的前端语法树在新进程中由同一库文件恢复。
        for command in LIBRARIES:
            run(command)
        run("read_verilog -icells -lib -specify -overwrite +/xilinx/abc9_model.v")
        inventory = json.loads(Path(spec["inventory"]).read_text())
        names = inventory["modules"]
        before = interfaces(design, names)
        expected = {name: [tuple(port) for port in ports] for name, ports in inventory["interfaces"].items()}
        if before != expected:
            raise RuntimeError("设计检查点的模块端口与初始设计不一致")
        if spec["mode"] == "batch":
            if len(spec["modules"]) != len(set(spec["modules"])) or not set(spec["modules"]) <= set(names):
                raise RuntimeError("批次模块清单包含重复或未知模块")
            if any(design.module(name).has_attribute("\\npu_abc9_leaf_module") for name in names):
                raise RuntimeError("输入设计包含保留的叶模块选择属性")
            leaf_names = [name for name in spec["modules"]
                          if spec.get("isolate_leaves") and combinational_leaf(design.module(name))]
            if leaf_names:
                map_leaves(design, leaf_names, specification, spec["abc9"])
            remaining = [name for name in spec["modules"] if name not in set(leaf_names)]
            for name in spec["modules"]:
                if name not in names:
                    raise RuntimeError("批次包含初始设计之外的模块：" + name)
                module = design.module(name)
                if module.has_attribute("\\npu_abc9_batch_module"):
                    raise RuntimeError("输入设计包含保留的批次选择属性")
                if name in remaining:
                    module.set_bool_attribute("\\npu_abc9_batch_module", True)
            run("select A:npu_abc9_batch_module")
            selected = [str(module.name) for module in design.selected_unboxed_whole_modules_warn()]
            if set(selected) != set(remaining) or len(selected) != len(remaining):
                raise RuntimeError("ABC9 的完整模块选择与批次清单不一致")
            print("ABC9_BATCH_MODULES " + json.dumps(selected), flush=True)
            if selected:
                run(spec["abc9"])
            run("select -clear")
            run("setattr -mod -unset npu_abc9_batch_module")
            if interfaces(design, names) != expected:
                raise RuntimeError("ABC9 改变了设计的模块端口")
        elif spec["mode"] == "finish":
            for command in spec["suffix"]:
                run(command)
            top = shlex.quote(spec["top"])
            run(f"synth_xilinx -top {top} -family xc7 -noiopad -noclkbuf -flatten -run finalize:")
            for command in ("setattr -mod -unset keep_hierarchy", "setattr -unset keep_hierarchy",
                            "flatten -noscopeinfo", "opt_clean", "check -assert", "stat -tech xilinx"):
                run(command)
            run("write_json " + shlex.quote(spec["mapped_json"]))
            for command in ("clkbufmap -buf BUFG O:I",
                            "iopadmap -bits -inpad IBUF O:I -outpad OBUF I:O", "clean",
                            "check -assert", "blackbox =A:whitebox"):
                run(command)
            run("write_verilog -noattr -noexpr " + shlex.quote(spec["mapped_verilog"]))
            return
        else:
            raise ValueError("未知的 ABC9 工作步骤")
    run("select -clear")
    run("bufnorm -conn")
    run("check -assert")
    run("write_rtlil " + shlex.quote(spec["output"]))


def discover_profile(folder, env):
    """从本机实际执行记录核对外层步骤，读取 ABC9 的完整参数。"""
    from open_fpga_synth import run_stage
    source = folder / "profile.sv"
    source.write_text("module abc9_profile(input wire[3:0] a,output wire y);\n"
                      "assign y=(a[0]&a[1])^(a[2]|a[3]);\nendmodule\n")
    script = folder / "profile.ys"
    script.write_text("read_verilog " + shlex.quote(str(source)) + "\n"
        "synth_xilinx -top abc9_profile -family xc7 -noiopad -noclkbuf -flatten -run begin:map_luts\n"
        "echo on\nsynth_xilinx -top abc9_profile -family xc7 -noiopad -noclkbuf -flatten -run map_luts:finalize\n")
    log = folder / "profile.log"
    measurement = run_stage(script, log, env)
    commands = re.findall(r"^yosys> (.*)$", log.read_text(), re.M)
    positions = [index for index, command in enumerate(commands) if command.startswith("abc9 ")]
    if len(positions) != 1 or commands[1:positions[0]] != PREFIX:
        raise RuntimeError("本机 Xilinx ABC9 前置步骤需要重新核对")
    end = commands.index("setattr -mod -unset abc9_box_id", positions[0])
    if commands[end + 1:] != SUFFIX:
        raise RuntimeError("本机 Xilinx ABC9 后置步骤需要重新核对")
    return {"prefix": PREFIX, "abc9": commands[positions[0]], "suffix": SUFFIX,
            "log_sha256": digest(log), "script_sha256": digest(script), "measurement": measurement}


def materialize(checkpoint, destination):
    with gzip.open(checkpoint, "rb") as source, destination.open("wb") as output:
        shutil.copyfileobj(source, output)


def save_checkpoint(source, destination):
    checksum = digest(source)
    temporary = destination.with_name(destination.name + ".tmp")
    with source.open("rb") as stream, gzip.open(temporary, "wb", compresslevel=3) as output:
        shutil.copyfileobj(stream, output)
    temporary.replace(destination)
    if digest(destination, compressed=True) != checksum:
        raise RuntimeError("完整 RTLIL 检查点压缩校验失败")
    return checksum


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--top")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--mapped-json", type=Path)
    parser.add_argument("--mapped-verilog", type=Path)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--keep-checkpoints", action="store_true")
    parser.add_argument("--isolate-leaves", action="store_true",
                        help="独立映射无状态组合叶模块，并在合并前逐模块证明等价")
    args = parser.parse_args()
    if args.worker:
        worker(args.worker)
        return
    if not all((args.input, args.top, args.out, args.mapped_json, args.mapped_verilog)):
        parser.error("需要 --input、--top、--out、--mapped-json 和 --mapped-verilog")
    if args.batch_size < 1:
        parser.error("--batch-size 必须为正整数")
    import pyosys
    from pyosys import libyosys as yosys
    from open_fpga_synth import run_stage
    folder = args.out.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PATH"] = str(Path(pyosys.__file__).parent) + os.pathsep + env.get("PATH", "")
    identity = {"input_sha256": digest(args.input, compressed=args.input.suffix == ".gz"),
                "top": args.top, "batch_size": args.batch_size,
                "isolate_leaves": args.isolate_leaves,
                "connection_representation": "direct",
                "tool": yosys.yosys_maybe_version(), "mapper_sha256": digest(Path(__file__)),
                "library_sha256": {name: digest(Path(pyosys.__file__).parent / "share" / name)
                    for name in ("xilinx/cells_sim.v", "xilinx/cells_xtra.v", "xilinx/abc9_model.v",
                                 "xilinx/lut_map.v", "xilinx/cells_map.v", "abc9_map.v", "abc9_unmap.v")}}
    status_path, inventory_path = folder / "progress.json", folder / "inventory.json"
    profile = discover_profile(folder, env)
    identity["mapping_commands"] = {name: profile[name] for name in ("prefix", "abc9", "suffix")}
    if args.resume and status_path.exists():
        status = json.loads(status_path.read_text())
        if status["identity"] != identity:
            raise RuntimeError("ABC9 检查点与当前输入、工具或映射参数不一致")
        if digest(inventory_path) != status["inventory_sha256"]:
            raise RuntimeError("ABC9 模块清单与检查点摘要不一致")
        checkpoint = folder / status["checkpoint"]
        if digest(checkpoint, compressed=True) != status["checkpoint_sha256"]:
            raise RuntimeError("ABC9 完整设计检查点与保存摘要不一致")
    else:
        status = {"identity": identity, "profile": profile, "completed_modules": [], "stages": []}
        checkpoint = None
    input_path, output_path = folder / "worker_input.il", folder / "worker_output.il"

    def execute(name, specification):
        spec = folder / (name + ".json")
        write_json(spec, specification)
        command = [sys.executable, str(Path(__file__).resolve()), "--worker", str(spec)]
        result = run_stage(spec, folder / (name + ".log"), env, command)
        process_ids = re.findall(r"^ABC9_WORKER_PID (\d+)$", (folder / (name + ".log")).read_text(), re.M)
        if len(process_ids) != 1:
            raise RuntimeError("工作进程记录不完整")
        result["worker_pid"] = int(process_ids[0])
        result["equivalent_leaf_modules"] = sum(map(int, re.findall(
            r"ABC9_LEAF_PROOFS (\d+)", (folder / (name + ".log")).read_text())))
        result["mapped_leaf_functions"] = sum(map(int, re.findall(
            r"ABC9_LEAF_FUNCTIONS (\d+)", (folder / (name + ".log")).read_text())))
        result["specification_sha256"] = digest(spec)
        return result

    def commit_checkpoint(name, result, completed):
        nonlocal checkpoint
        next_checkpoint = folder / (name + ".il.gz")
        checksum = save_checkpoint(output_path, next_checkpoint)
        result.update(output_sha256=checksum, checkpoint=next_checkpoint.name)
        status["stages"].append(result)
        status.update(checkpoint=next_checkpoint.name, checkpoint_sha256=checksum,
                      inventory_sha256=digest(inventory_path), completed_modules=completed)
        write_json(status_path, status)
        previous, checkpoint = checkpoint, next_checkpoint
        if previous is not None and not args.keep_checkpoints and previous != checkpoint:
            previous.unlink()
        output_path.unlink()
        input_path.unlink(missing_ok=True)
        print("ABC9_CHECKPOINT", name, "modules=" + str(len(completed)), flush=True)

    if checkpoint is None:
        source = args.input.resolve()
        if source.suffix == ".gz":
            materialize(source, input_path)
            source = input_path
        result = execute("00_prepare", {"mode": "prepare", "input": str(source),
            "output": str(output_path), "inventory": str(inventory_path), "prefix": profile["prefix"]})
        commit_checkpoint("00_prepare", result, [])
    inventory = json.loads(inventory_path.read_text())
    names = inventory["modules"]
    done = status["completed_modules"]
    if names[:len(done)] != done:
        raise RuntimeError("已完成模块与完整模块顺序不一致")
    for start in range(len(done), len(names), args.batch_size):
        selected = names[start:start + args.batch_size]
        materialize(checkpoint, input_path)
        label = f"batch_{start // args.batch_size + 1:04d}"
        result = execute(label, {"mode": "batch", "input": str(input_path),
            "output": str(output_path), "inventory": str(inventory_path),
            "modules": selected, "abc9": profile["abc9"], "isolate_leaves": args.isolate_leaves})
        result["modules"] = selected
        commit_checkpoint(label, result, names[:start + len(selected)])
    materialize(checkpoint, input_path)
    result = execute("finish", {"mode": "finish", "input": str(input_path),
        "inventory": str(inventory_path), "top": args.top, "suffix": profile["suffix"],
        "mapped_json": str(args.mapped_json.resolve()), "mapped_verilog": str(args.mapped_verilog.resolve())})
    input_path.unlink()
    result.update(mapped_json_sha256=digest(args.mapped_json), mapped_verilog_sha256=digest(args.mapped_verilog))
    report = {"passed": True, "identity": identity, "profile": profile,
              "module_count": len(names), "batch_count": len(status["stages"]) - 1,
              "checkpoint": str(checkpoint), "checkpoint_sha256": status["checkpoint_sha256"],
              "all_module_interfaces_preserved": True, "stages": status["stages"], "finish": result}
    write_json(folder / "summary.json", report)
    print("ABC9_BATCH_MAPPING_PASS", "modules=" + str(len(names)), "batches=" + str(report["batch_count"]), flush=True)


if __name__ == "__main__":
    main()
