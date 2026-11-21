#!/usr/bin/env python3
"""使用官方 FPGA 原语模型执行生产参数下的完整 NPU 功能回归。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/fpga_integration")
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--build-timeout", type=int, default=7200)
    parser.add_argument('--source-root', type=Path, default=ROOT,
                        help='与完整 SoC 测量一致的固定 RTL 目录')
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / "scripts/fpga"))
    from open_fpga_synth import CASES, production_configuration
    import pyosys

    configuration = production_configuration()
    source_root = args.source_root.resolve()
    if digest(source_root / configuration['path']) != configuration['sha256']:
        raise RuntimeError('固定源码的生产配置与当前测试参数不同')
    top_source = source_root / 'rtl/axi_top/npu_axil_top.sv'
    line_match = re.search(r'parameter\s+(?:int\s+)?CONV_LINE_BYTES\s*=\s*(\d+)\s*,',
                           top_source.read_text())
    if line_match is None:
        raise RuntimeError('无法读取生产顶层的缓存行长度')
    cache_line_bytes = int(line_match[1])
    soc_parameters = CASES['soc_top']['parameters']
    soc_source = source_root / 'rtl/soc_top.sv'
    address_match = re.search(r'parameter\s+AXI_ADDR_WIDTH\s*=\s*(\d+)\s*,', soc_source.read_text())
    if address_match is None:
        raise RuntimeError('无法读取完整 SoC 的地址宽度')
    address_width = soc_parameters.get('NPU_ADDR_WIDTH',
        soc_parameters.get('AXI_ADDR_WIDTH', int(address_match[1])))
    vector_pe_count = soc_parameters['VECTOR_PE_COUNT']
    ps_storage_rows = soc_parameters.get('PS_STORAGE_ROWS',
        (3 * int(configuration['values']['SIZE']) - 1) *
        (int(configuration['values']['PS_FRAME_COUNT']) + 1))
    fifo_match = re.search(r'parameter\s+(?:int\s+(?:unsigned\s+)?)?OA_S16_FIFO_BANKS_MAX\s*=\s*(\d+)\s*,',
                           soc_source.read_text())
    if fifo_match is None:
        raise RuntimeError('无法读取完整 SoC 的 INT16 写回 FIFO 容量')
    oa_s16_fifo_banks_max = soc_parameters.get('OA_S16_FIFO_BANKS_MAX', int(fifo_match[1]))
    values = configuration["values"]
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    executable = shutil.which(args.verilator)
    if executable is None:
        raise RuntimeError("Cannot find Verilator: " + args.verilator)
    library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
    model_names = ("LUT1", "LUT2", "LUT3", "LUT4", "LUT5", "LUT6", "LUT6_2",
                   "MUXF7", "MUXF8", "DSP48E1", "FDRE", "CARRY4")
    library_text = library.read_text()
    models = []
    for name in model_names:
        match = re.search(r"^module " + name + r"\b.*?^endmodule", library_text,
                          re.MULTILINE | re.DOTALL)
        if match is None:
            raise RuntimeError("Missing official functional model: " + name)
        models.append(match.group(0))
    model_path = out / "xilinx_primitives.sv"
    model_path.write_text("\n\n".join(models) + "\n")
    observer_paths, observer_models = {}, {}
    observer_directory = out / "observers"
    observer_directory.mkdir(exist_ok=True)
    for source in sorted((ROOT / "test/monitors").glob("*.sv")):
        content = source.read_text()
        opening = "`ifndef SYNTHESIS\n"
        start, end = content.find(opening), content.rfind("`endif")
        if start < 0 or end < start or content[end + len("`endif"):].strip():
            raise RuntimeError("Unexpected observer guard: " + str(source))
        destination = observer_directory / source.name
        destination.write_text(content[:start] + content[start + len(opening):end] +
                               content[end + len("`endif"):])
        observer_paths[str(source)] = str(destination)
        observer_models[str(source.relative_to(ROOT))] = {
            "source_sha256": digest(source), "model_sha256": digest(destination)}
    wrapper = out / "verilator_xilinx"
    simulation_defines = ["SYNTHESIS=1", "XILINX_FPGA=1"]
    wrapper.write_text("#!" + sys.executable + "\nimport os, sys\n" +
                       "observers = " + repr(observer_paths) + "\n" +
                       "arguments = [observers.get(argument, argument) for argument in sys.argv[1:]]\n" +
                       "command = " + repr([executable, *["-D" + value for value in simulation_defines],
                                             str(model_path)]) + " + arguments\n" +
                       "os.execv(command[0], command)\n")
    wrapper.chmod(0o755)
    command = [sys.executable, str(ROOT / "test/conv_npu/run.py"),
               "--out", str(out / "npu"), "--verilator", str(wrapper),
               '--source-root', str(source_root),
               "--jobs", str(args.jobs), "--sizes", values["SIZE"],
               "--build-timeout", str(args.build_timeout),
               "--bus-width", values["NPU_AXI_DATA_WIDTH"],
               "--cache-bytes", values["IM2COL_CACHE_BYTES"],
               '--cache-line-bytes', str(cache_line_bytes),
               '--address-width', str(address_width), '--vector-pe-count', str(vector_pe_count),
               '--ps-storage-rows', str(ps_storage_rows),
               '--oa-s16-fifo-banks-max', str(oa_s16_fifo_banks_max),
               "--shared-bank-bytes", values["SHARED_BANK_BYTES"],
               "--shared-bank-count", values["SHARED_BANK_COUNT"],
               "--ps-compress", "--force-raw", "--pool-bytes", values["PS_POOL_BYTES"]]
    with (out / "run.log").open("w") as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    report_path = out / "npu/summary.json"
    npu = json.loads(report_path.read_text()) if report_path.is_file() else {}
    report = dict(passed=result.returncode == 0 and npu.get("passed", False),
                  source_root=str(source_root),
                  cache_line_bytes=cache_line_bytes, cache_parameter_source_sha256=digest(top_source),
                  address_width=address_width, vector_pe_count=vector_pe_count,
                  ps_storage_rows=ps_storage_rows, oa_s16_fifo_banks_max=oa_s16_fifo_banks_max,
                  soc_parameter_source_sha256=digest(soc_source),
                  configuration=configuration, simulation_defines=simulation_defines,
                  primitive_models=list(model_names),
                  observer_models=observer_models,
                  primitive_library_sha256=digest(library), generated_models_sha256=digest(model_path),
                  wrapper_sha256=digest(wrapper), runner_sha256=digest(Path(__file__)),
                  command=command, returncode=result.returncode,
                  tasks=npu.get("task_count", 0), int32_checks=npu.get("int32_checks", 0),
                  npu_report=str(report_path))
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("passed", "tasks", "int32_checks", "primitive_models")}))
    if not report["passed"]:
        raise RuntimeError("FPGA integration regression failed: " + str(out / "run.log"))


if __name__ == "__main__":
    main()
