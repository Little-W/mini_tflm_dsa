#!/usr/bin/env python3
"""使用生产 NPU 和官方 FPGA 模型比较配置有效信号的两种表达式。"""
import argparse
import filecmp
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(values, log, timeout=1800):
    with log.open("w") as stream:
        stream.write(shlex.join([str(x) for x in values]) + "\n")
        stream.flush()
        result = subprocess.run([str(x) for x in values], cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise RuntimeError(str(log) + "\n" + log.read_text()[-7000:])


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError("被测源码结构不符: " + old)
    return text.replace(old, new, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verilator", default="verilator-modern")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    generated = out / "generated"
    generated.mkdir(exist_ok=True)
    source_paths = [ROOT / "rtl/npu/conv/conv_im2col_pkg.sv", ROOT / "rtl/npu/conv/vector_engine_pkg.sv"]
    source_paths += [p for folder in ("rtl/npu", "rtl/common") for p in sorted((ROOT/folder).rglob("*"))
                     if p.suffix in (".sv", ".v") and p not in source_paths]
    changed = {}
    for name in ("rtl/npu/conv/vector_engine.sv", "rtl/npu/top/npu_top.sv", "rtl/npu/dma/axi_dual_block_dma.sv"):
        path = ROOT / name
        text = path.read_text()
        if path.name == "vector_engine.sv":
            port_end=text.index("\n);")
            text=text[:port_end]+",\n  input logic proof_offer_enable"+text[port_end:]
            expression=next((value for value in ("dma_cfg_valid = state==CONFIGURE && dma_cfg_ready;",
                            "dma_cfg_valid = state==CONFIGURE;") if text.count(value)==1),None)
            if expression is None:
                raise RuntimeError("向量配置有效表达式不符")
            text = replace_once(text, expression,
                                "dma_cfg_valid = state==CONFIGURE && (proof_offer_enable || dma_cfg_ready);")
        elif path.name == "npu_top.sv":
            port_end=text.index("\n);")
            text=text[:port_end]+",\n    input logic proof_offer_enable"+text[port_end:]
            text = replace_once(text, ".dma_cfg_valid(vector_dma_cfg_valid), .dma_cfg_ready(conv_cfg_ready && run_vector),",
                                ".proof_offer_enable(proof_offer_enable),\n            "
                                ".dma_cfg_valid(vector_dma_cfg_valid), .dma_cfg_ready(conv_cfg_ready && run_vector),")
        else:
            # 等待场景仅在接收端扩展背压，配置事件仍由实际 cfg_fire 产生。
            text = replace_once(text, ".cfg_ready(fe_cfg_ready),", ".cfg_ready(proof_raw_fe_cfg_ready),")
            text = replace_once(text, "endmodule", '''
    logic proof_raw_fe_cfg_ready;
    integer proof_ready_hold=0;
    integer proof_elapsed;
    initial begin
        if (!$value$plusargs("ready_hold=%d",proof_ready_hold)) proof_ready_hold=0;
    end
    always_ff @(posedge clk) begin
        if (!rst_n) proof_elapsed<=0;
        else if (proof_elapsed<proof_ready_hold) proof_elapsed<=proof_elapsed+1;
    end
    assign fe_cfg_ready=proof_raw_fe_cfg_ready && proof_elapsed>=proof_ready_hold;
endmodule''')
        destination = generated / path.name
        destination.write_text(text)
        changed[path] = destination
    import pyosys
    library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
    models = []
    for primitive in ("LUT1", "LUT2", "LUT3", "LUT4", "LUT5", "LUT6", "LUT6_2",
                      "MUXF7", "MUXF8", "DSP48E1", "FDRE", "CARRY4"):
        match = re.search(r"^module " + primitive + r"\b.*?^endmodule", library.read_text(), re.M|re.S)
        if not match:
            raise RuntimeError("缺少官方模型: " + primitive)
        models.append(match[0])
    model_file = generated / "primitives.sv"
    model_file.write_text("\n\n".join(models) + "\n")
    original = source_paths + [HERE / "system_top.sv", HERE / "system_main.cpp",
                               ROOT / "config/npu_fpga.mk"]
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in original}
    source_list = [changed.get(p,p) for p in source_paths]
    source_list += [model_file, HERE / "system_top.sv"]
    manifest = {"source_sha256": hashes, "generated_sha256": {str(p.name): digest(p) for p in changed.values()},
                "primitive_library_sha256": digest(library), "primitive_models_sha256": digest(model_file),
                "size":16,"bus_width":64,"shared_bank_bytes":8192,"shared_bank_count":7,
                "pe_count":8,"ps_frames":16,"im2col_cache_bytes":4096}
    manifest_path = out / "build.json"
    if not args.skip_build:
        verilator = shutil.which(args.verilator)
        if not verilator:
            raise RuntimeError("找不到 Verilator")
        values = [verilator,"--cc","--exe","--assert","--top-module","vector_offer_system_top",
                  "-Wno-fatal","-Wno-PINMISSING","--Mdir",out/"obj","--output-groups","0",
                  "--output-split","12000","--output-split-cfuncs","200",
                  "-DSYNTHESIS=1","-DXILINX_FPGA=1","-DGEMPACT_PS_COMPRESS=1",
                  "-DGEMMORA_PS_POOL_BYTES=49152","-DGEMMORA_PS_FORCE_RAW=1",
                  "-CFLAGS","-std=c++17 --param=ggc-min-expand=5 --param=ggc-min-heapsize=4096",
                  ROOT/"test/conv_npu/simulator.vlt",*source_list,HERE/"system_main.cpp"]
        command(values,out/"verilate.log")
        command(["make","-C",out/"obj","-f","Vvector_offer_system_top.mk","-j",args.jobs,
                 "OPT_FAST=-O1","OPT_SLOW=-O0","OPT_GLOBAL=-O1","VK_PCH_I_FAST=", "VK_PCH_I_SLOW=",
                 "CFG_CXXFLAGS_PCH=-E"],out/"compile.log")
        manifest_path.write_text(json.dumps(manifest,indent=2)+"\n")
    else:
        saved=json.loads(manifest_path.read_text())
        saved["source_sha256"].pop(str(Path(__file__).resolve().relative_to(ROOT)),None)
        if saved != manifest:
            raise RuntimeError("源码或参数与已构建模型不一致")
        manifest_path.write_text(json.dumps(manifest,indent=2)+"\n")
    binary = out / "obj/Vvector_offer_system_top"
    runs = []
    for hold in (0,400):
        logs = []
        for offer in (0,1):
            log = out / f"hold{hold}_offer{offer}.log"
            trace=out/f"hold{hold}_offer{offer}.bin"
            command([binary,f"+ready_hold={hold}",f"+trace={trace}",*(["--offer"] if offer else [])],log)
            text = log.read_text().splitlines()[1:]
            if not any("VECTOR_CONFIGURATION_SYSTEM_PASS" in line for line in text):
                raise RuntimeError("系统结果不完整")
            logs.append(text)
        if logs[0] != logs[1]:
            raise RuntimeError("公开输出或任务周期不同")
        if not filecmp.cmp(out/f"hold{hold}_offer0.bin",out/f"hold{hold}_offer1.bin",shallow=False):
            raise RuntimeError("逐周期公开输出记录不同")
        fields = dict(re.findall(r"(\w+)=(\w+)",logs[0][-1]))
        if hold and int(fields["wait"]) == 0:
            raise RuntimeError("未覆盖配置等待")
        runs.append({"ready_hold_cycles":hold,"passed":True,"public_outputs_and_cycles_equal":True,
                     "public_trace_bytes":(out/f"hold{hold}_offer0.bin").stat().st_size,
                     "public_trace_sha256":digest(out/f"hold{hold}_offer0.bin"),
                     "ordinary_clients_mutually_exclusive_for_entire_vector_task":True,
                     "statistics":fields,"logs_sha256":{f"offer{x}":digest(out/f"hold{hold}_offer{x}.log") for x in (0,1)}})
    if hashes != {str(p.relative_to(ROOT)):digest(p) for p in original}:
        raise RuntimeError("受测源码在验证期间变化")
    report = {"passed":True,"source_revision":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
              "runner_sha256":digest(Path(__file__).resolve()),
              "build":manifest,"binary_sha256":digest(binary),"runs":runs}
    (out/"summary.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    print(json.dumps({"passed":True,"runs":runs},ensure_ascii=False),flush=True)


if __name__ == "__main__":
    main()
