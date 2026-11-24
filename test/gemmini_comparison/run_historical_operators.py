#!/usr/bin/env python3
"""使用固定历史源码运行共同算子，并检查原始 RTL 与 Git 对象一致。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import run_storage_operators as current

REVISION = "7142f8ee41342454d9e27cae078c8e35a584685c"


def snapshot(root):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args])
    if git("rev-parse", "HEAD").decode().strip() != REVISION:
        raise ValueError("历史实验要求指定的远端提交")
    if git("status", "--porcelain", "--untracked-files=no").strip():
        raise ValueError("历史实验的仓库源码必须保持干净")
    result = {}
    for entry in git("ls-tree", "-rz", REVISION).split(b"\0"):
        if not entry:
            continue
        description, name = entry.split(b"\t", 1)
        mode, kind, expected = description.decode().split()
        relative = name.decode()
        path = root / relative
        if kind != "blob" or not path.is_file():
            continue
        data = os.readlink(path).encode() if mode == "120000" else path.read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if actual != expected:
            raise ValueError("历史源码与 Git 对象不同: " + relative)
        result[relative] = hashlib.sha256(data).hexdigest()
    for required in ("rtl/npu/top/npu_top.sv", "rtl/npu/conv/conv_im2col_frontend.sv",
                     "test/gemmini_comparison/run_storage_operators.py"):
        if required not in result:
            raise ValueError("缺少历史实验输入: " + required)
    return result


def instrument_testbench(text):
    """历史顶层参数保持原定义，观察和外存服务使用共同检查。"""
    instance = "    conv_test_axi_memory #("
    ports = "        .arvalid, .arready, .araddr, .arlen, .arsize, .arburst,"
    check = '        assert (errors == 0) else $fatal(1, "Operator output or memory preservation mismatch");'
    for marker in (instance, ports, check):
        if text.count(marker) != 1:
            raise ValueError("无法识别历史测试台的共同检查位置")
    text = text.replace(instance, current.ar_interval_monitor() + "\n" + instance)
    text = text.replace(ports, "        .arvalid(memory_arvalid), .arready(memory_arready), .araddr, .arlen, .arsize, .arburst,")
    text = text.replace("    initial begin : run_case", current.output_tensor_dump() + "\n    initial begin : run_case")
    text = text.replace(check, check + "\n        write_output_tensor();")
    text = text.replace("conv_low_latency=%0d ", "")
    text = text.replace("            u_dut.CONV_LOW_LATENCY,\n", "")
    text = text.replace('conv_register_descriptor=%0d",',
                        'conv_register_descriptor=%0d conv_register_cache_request=%0d",')
    text = text.replace("u_dut.u_block_dma_arbiter.u_dma.g_im2col.u_frontend.REGISTER_DESCRIPTOR);",
                        "u_dut.u_block_dma_arbiter.u_dma.g_im2col.u_frontend.REGISTER_DESCRIPTOR, 0);")
    return text


def verify_manifests(root, out, expected, mode):
    repository, support, rtl = {}, {}, {}
    for name in ("sim/build.json", "planner/build.json"):
        manifest = json.loads((out / name).read_text())
        if manifest.get("returncode") != 0 or not manifest["sources_unchanged_during_build"]:
            raise ValueError("历史实验编译未完成或源码发生变化")
        for name, checksum in manifest["source_sha256"].items():
            path = Path(name)
            if current.digest(path) != checksum:
                raise ValueError("编译输入摘要发生变化: " + name)
            if path.is_relative_to(root):
                relative = str(path.relative_to(root))
                if expected.get(relative) != checksum:
                    raise ValueError("编译输入不属于固定 Git 源码: " + relative)
                repository[relative] = checksum
                if relative.startswith("rtl/"):
                    rtl[relative] = checksum
            else:
                support[name] = checksum
    build = json.loads((out / "sim/build.json").read_text())
    macro = "-DTB_CONV_LOW_LATENCY=" + str(int(mode == "low-latency"))
    if macro not in build["command"] or not {"-DSYNTHESIS=1", "-DXILINX_FPGA=1", "--assert"}.issubset(build["command"]):
        raise ValueError("历史实验编译参数不同")
    for required in ("rtl/npu/top/npu_top.sv", "rtl/npu/conv/conv_im2col_frontend.sv"):
        if required not in rtl:
            raise ValueError("编译记录缺少生产 RTL: " + required)
    return {"passed": True, "source_revision": REVISION, "source_root": str(root), "mode": mode,
            "sources_unchanged": True, "production_rtl_sha256": rtl,
            "compiled_and_planner_repository_sources": repository,
            "verification_support_sha256": support,
            "binary_sha256": build["binary_sha256"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("--mode", choices=("default", "low-latency"), required=True)
    selected, remaining = parser.parse_known_args()
    paths = argparse.ArgumentParser(add_help=False)
    paths.add_argument("--repo", type=Path, required=True)
    paths.add_argument("--out", type=Path, required=True)
    location, unused = paths.parse_known_args(remaining)
    root, out = location.repo.resolve(), location.out.resolve()
    before = snapshot(root)
    old_file = root / "test/gemmini_comparison/run_storage_operators.py"
    spec = importlib.util.spec_from_file_location("historical_storage_operators", old_file)
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    low_latency = selected.mode == "low-latency"
    original_build = current.build

    def profile(args, normalize):
        args.conv_low_latency = low_latency
        args.verification_sources = [Path(__file__).resolve(), old_file]
        result = legacy.hardware_profile(args, normalize)
        result["conv_register_cache_request"] = 0
        result["rtl_simulation_defines"] = [name for name, enabled in
                                           (("SYNTHESIS", args.synthesis), ("XILINX_FPGA", args.fpga)) if enabled]
        result["historical_revision"] = REVISION
        result["historical_mode"] = selected.mode
        return result

    def testbench(args):
        return instrument_testbench(legacy.testbench(args))

    def build(args, runner, hardware):
        execute = runner.command

        def compile_command(command, *arguments, **keywords):
            if command and command[0] == args.verilator:
                command.insert(1, "-DTB_CONV_LOW_LATENCY=" + str(int(low_latency)))
            return execute(command, *arguments, **keywords)

        runner.command = compile_command
        try:
            return original_build(args, runner, hardware)
        finally:
            runner.command = execute

    current.hardware_profile = profile
    current.testbench = testbench
    current.build = build
    sys.argv = [str(Path(current.__file__).resolve()), *remaining]
    status = current.main()
    after = snapshot(root)
    if after != before:
        raise ValueError("历史实验源码发生变化")
    if status == 0 and (out / "summary.json").exists():
        current.write_json(out / "historical_source_verification.json",
                           verify_manifests(root, out, before, selected.mode))
    return status


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
