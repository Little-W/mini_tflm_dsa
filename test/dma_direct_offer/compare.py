#!/usr/bin/env python3
"""在真实 DMA 测试中比较全部公开输出及描述符控制状态。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/dma/axi_dual_block_dma.sv")


def comparison_source(current):
    header = current[:re.search(r"^\s*\);", current, re.MULTILINE).end()]
    parameters = re.findall(r"parameter\s+int\s+unsigned\s+(\w+)\s*=", header)
    outputs = []
    for line in header.splitlines():
        match = re.match(r"\s*output\s+logic\s+(signed\s+)?(\[[^\]]*\]\s*)?(.*)", line)
        if match is None:
            continue
        signed, width, names = match.groups()
        for item in names.rstrip(", ").split(","):
            name = re.fullmatch(r"\s*(\w+)\s*(\[[^\]]*\])?\s*", item)
            if name is None:
                raise ValueError("Unrecognized output declaration: " + line)
            outputs.append((name[1], signed or "", width or "", name[2] or ""))
    declarations = [f"logic {signed}{width}ref_{name}{array};" for name, signed, width, array in outputs]
    connection = ",\n".join(f".{name}(ref_{name})" for name, _, _, _ in outputs) + ",\n.*"
    parameter_map = ",".join(f".{name}({name})" for name in parameters)
    scalar = [name for name, _, _, array in outputs if not array]
    current_scalar = ",".join(scalar)
    reference_scalar = ",".join("ref_" + name for name in scalar)
    checks = [f"if ({{{current_scalar}}} !== {{{reference_scalar}}}) "
              "$fatal(1,\"DMA public scalar output mismatch cycle=%0d\", compared_cycles);"]
    for name, _, _, array in outputs:
        if array:
            checks.append(f"for(integer i=0;i<$size({name});i=i+1) "
                          f"if({name}[i] !== ref_{name}[i]) "
                          f"$fatal(1,\"DMA {name} mismatch cycle=%0d lane=%0d\",compared_cycles,i);")
    states = ("job_conv", "job_range", "conv_active", "conv_pending", "conv_finished",
              "conv_command_error", "conv_done_r", "conv_done_error", "descriptor_error",
              "command_im2col", "p0_q", "q0_q", "group_q", "rows_q", "cols_q", "slot_q")
    checks.append("if ({" + ",".join(states) + "} !== {" +
                  ",".join("u_reference." + name for name in states) + "}) "
                  "$fatal(1,\"DMA descriptor state mismatch cycle=%0d\",compared_cycles);")
    frontend_states = ("state", "configured", "error", "tile_error", "p0", "q0", "row_idx",
                       "col_idx", "rows_q", "cols_q", "slot_q", "ix", "iy", "addr")
    checks.append("if (CONV_SUPPORTED) begin\nif ({" +
                  ",".join("g_im2col.u_frontend." + name for name in frontend_states) + "} !== {" +
                  ",".join("u_reference.g_im2col.u_frontend." + name for name in frontend_states) +
                  "}) $fatal(1,\"Frontend descriptor state mismatch cycle=%0d\",compared_cycles);\nend")
    monitor = "\n" + "\n".join(declarations) + f"""
integer compared_cycles=0;
integer stalled_offers=0;
reference_axi_dual_block_dma #({parameter_map}) u_reference (
{connection}
);
always @(posedge clk) begin
  #1;
  if(rst_n) begin
    compared_cycles=compared_cycles+1;
    if(direct_offer && !fe_tile_ready) stalled_offers=stalled_offers+1;
    {chr(10).join(checks)}
  end
end
final $display("DMA_DIRECT_COMPARE_PASS outputs={len(outputs)} cycles=%0d stalled_offers=%0d",compared_cycles,stalled_offers);
"""
    position = current.rindex("endmodule")
    return current[:position] + monitor + current[position:], len(outputs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-ref", default="151b87d5")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verilator", default="verilator")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = read_rtl_source(f"{args.reference_ref}:{SOURCE}", cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    reference = out / "reference_dual.sv"
    reference.write_text(original.replace("module axi_dual_block_dma", "module reference_axi_dual_block_dma", 1))
    compared = out / "compared_dual.sv"
    instrumented, output_count = comparison_source(current)
    compared.write_text(instrumented)
    spec = importlib.util.spec_from_file_location("conv_dma_test", ROOT / "test/conv_dma/run.py")
    suite = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(suite)
    cases = [("matrix4", "tb_conv_dma", ROOT / "test/conv_dma/tb_conv_dma.sv", 4, True, "CONV_DMA_PASS"),
             ("matrix16", "tb_conv_dma", ROOT / "test/conv_dma/tb_conv_dma.sv", 16, True, "CONV_DMA_PASS"),
             ("dual", "tb_axi_dual_block_dma", ROOT / "test/axi_dual_block_dma/tb_axi_dual_block_dma.sv",
              8, False, "[AXI_DUAL_DMA] ALL PASS"),
             ("arbiter", "tb_axi_block_dma_arbiter", ROOT / "test/axi_block_dma_arbiter/tb_axi_block_dma_arbiter.sv",
              8, False, "[AXI_ARB] ALL PASS")]
    runs = []
    for name, top, bench, size, memory, marker in cases:
        folder = out / name
        folder.mkdir(exist_ok=True)
        sources = [compared if path == ROOT / SOURCE else path for path in suite.sources(bench, memory)]
        sources.append(reference)
        hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
        command = [args.verilator, "--binary", "--timing", "--assert", "-sv", "--top-module", top,
                   "-Wno-fatal", f"-DTB_SIZE={size}", "--Mdir", str(folder / "obj"), "-j", "2",
                   "--output-groups", "0", "--output-split", "12000", "-CFLAGS", "-std=c++20 -O1",
                   "-MAKEFLAGS", "OPT_FAST=-O1 OPT_SLOW=-O0 VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E",
                   *map(str, sources)]
        with (folder / "build.log").open("w") as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        binary = folder / "obj" / ("V" + top)
        command = [str(binary)]
        if memory:
            command.append("+MATRIX_TRACE=" + str(folder / "matrix_returns.csv"))
        run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)
        (folder / "run.log").write_text(run.stdout + run.stderr)
        if marker not in run.stdout or "DMA_DIRECT_COMPARE_PASS" not in run.stdout:
            raise RuntimeError("Incomplete DMA comparison")
        if any(hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != before for path, before in hashes.items()):
            raise RuntimeError("Sources changed during comparison")
        result = dict(case=name, passed=True, source_sha256=hashes,
                      binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                      log_sha256=hashlib.sha256((folder / "run.log").read_bytes()).hexdigest(),
                      summary=[line for line in run.stdout.splitlines() if
                               line.startswith(("DMA_DIRECT_COMPARE_PASS", "CONV_DMA_PASS"))])
        runs.append(result)
        print(json.dumps({key: result[key] for key in ("case", "passed", "summary")}), flush=True)
        for path in (folder / "obj").iterdir():
            if path.suffix in (".o", ".gch"):
                path.unlink()
    if current != (ROOT / SOURCE).read_text():
        raise RuntimeError("DMA source changed during comparison")
    result = dict(passed=True, reference_ref=args.reference_ref, public_outputs=output_count,
                  source_sha256=hashlib.sha256(current.encode()).hexdigest(), runs=runs)
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print("DMA_DIRECT_COMPARE_PASS", out / "summary.json")


if __name__ == "__main__":
    main()
