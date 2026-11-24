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
        result[name] = sorted((str(wire.name), wire.width, wire.port_input, wire.port_output, wire.port_id)
                              for wire in module.wires_.values() if wire.port_input or wire.port_output)
    return result


def worker(specification):
    from pyosys import libyosys as yosys
    print("ABC9_WORKER_PID", os.getpid(), flush=True)
    spec = json.loads(specification.read_text())
    design = yosys.Design()
    run = lambda command: yosys.run_pass(command, design)
    run("read_rtlil " + shlex.quote(spec["input"]))
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
            for name in spec["modules"]:
                if name not in names:
                    raise RuntimeError("批次包含初始设计之外的模块：" + name)
                module = design.module(name)
                if module.has_attribute("\\npu_abc9_batch_module"):
                    raise RuntimeError("输入设计包含保留的批次选择属性")
                module.set_bool_attribute("\\npu_abc9_batch_module", True)
            run("select A:npu_abc9_batch_module")
            selected = [str(module.name) for module in design.selected_unboxed_whole_modules_warn()]
            if set(selected) != set(spec["modules"]) or len(selected) != len(spec["modules"]):
                raise RuntimeError("ABC9 的完整模块选择与批次清单不一致")
            print("ABC9_BATCH_MODULES " + json.dumps(selected), flush=True)
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
            "modules": selected, "abc9": profile["abc9"]})
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
