#!/usr/bin/env python3
"""逐周期验证寄存启动 DMA 的窗口接口、队列及数值结果。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "rtl/npu/dma/axi_dual_block_dma.sv"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-ref", default="ed458cee")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verilator", default="verilator")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location("dma_comparison", ROOT / "test/dma_direct_offer/compare.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    current = SOURCE.read_text()
    original = subprocess.check_output(["git", "show", f"{args.reference_ref}:{SOURCE.relative_to(ROOT)}"],
                                       cwd=ROOT, text=True)
    reference = out / "reference_dual.sv"
    reference.write_text(original.replace("module axi_dual_block_dma", "module reference_axi_dual_block_dma", 1))
    instrumented, output_count = helper.comparison_source(current)
    instrumented = instrumented.replace("if(direct_offer && !fe_tile_ready)", "if(conv_pending && !fe_tile_ready)")
    instrumented = instrumented.replace("DMA_DIRECT_COMPARE_PASS", "DMA_WINDOW_COMPARE_PASS")
    instrumented = instrumented.replace("always @(posedge clk) begin\n  #1;", "always @(negedge clk) begin")
    instrumented = instrumented.replace("integer stalled_offers=0;", "integer stalled_offers=0;\ninteger early_window_cycles=0;")
    instrumented = instrumented.replace("compared_cycles=compared_cycles+1;", "compared_cycles=compared_cycles+1;\n"
        "if(win_payload_select && !win_frontend_valid) early_window_cycles=early_window_cycles+1;")
    queue_fields = ("head", "tail", "count", "active", "failed")
    queue_current = "{" + ",".join("u_window_queue." + field for field in queue_fields) + "}"
    queue_reference = "{" + ",".join("u_reference.u_window_queue." + field for field in queue_fields) + "}"
    request = "{win_req_valid,win_req_ready,win_req_p0,win_req_q0,win_req_cols,win_req_tag}"
    response_fields = ("win_rsp_valid", "win_rsp_tag", "win_rsp_col", "win_rsp_data[0]", "win_rsp_data[1]",
                       "win_rsp_data[2]", "win_rsp_data[3]", "win_rsp_mask", "win_rsp_last", "win_rsp_error")
    response = "{" + ",".join(response_fields) + "}"
    reference_response = "{" + ",".join("ref_" + field for field in response_fields) + "}"
    queue_monitor = f"""
integer queue_trace;
string queue_trace_path;
initial begin
  if(!$value$plusargs("DMA_COMPARE_TRACE=%s",queue_trace_path)) $fatal(1,"Missing queue trace path");
  queue_trace=$fopen(queue_trace_path,"w");
  if(queue_trace==0) $fatal(1,"Cannot open queue trace");
  $fwrite(queue_trace,"cycle,request,rsp_ready,current_response,reference_response,current_queue,reference_queue");
  for(integer q=0;q<WINDOW_OUTSTANDING;q=q+1)
    $fwrite(queue_trace,",current_slot%0d,reference_slot%0d",q,q);
  $fwrite(queue_trace,"\\n");
end
always @(negedge clk) if(rst_n) begin
  if({queue_current} !== {queue_reference}) $fatal(1,"Window queue control mismatch");
  $fwrite(queue_trace,"%0d,%h,%b,%h,%h,%h,%h",compared_cycles,{request},win_rsp_ready,
          {response},{reference_response},{queue_current},{queue_reference});
  for(integer q=0;q<WINDOW_OUTSTANDING;q=q+1) begin
    if({{u_window_queue.p0[q],u_window_queue.q0[q],u_window_queue.cols[q],u_window_queue.tags[q]}} !==
       {{u_reference.u_window_queue.p0[q],u_reference.u_window_queue.q0[q],
         u_reference.u_window_queue.cols[q],u_reference.u_window_queue.tags[q]}})
      $fatal(1,"Window queue storage mismatch slot=%0d",q);
    $fwrite(queue_trace,",%h,%h",{{u_window_queue.p0[q],u_window_queue.q0[q],u_window_queue.cols[q],u_window_queue.tags[q]}},
       {{u_reference.u_window_queue.p0[q],u_reference.u_window_queue.q0[q],
         u_reference.u_window_queue.cols[q],u_reference.u_window_queue.tags[q]}});
  end
  $fwrite(queue_trace,"\\n");
end
final $fclose(queue_trace);
"""
    position = instrumented.rindex("endmodule")
    instrumented = instrumented[:position] + queue_monitor + "\nfinal begin\n"
    instrumented += "if(early_window_cycles==0) $fatal(1,\"No early window descriptors observed\");\n"
    instrumented += "$display(\"WINDOW_DESCRIPTOR_COMPARE_PASS early_window_cycles=%0d\",early_window_cycles);\nend\nendmodule\n"
    compared = out / "compared_dual.sv"
    compared.write_text(instrumented)
    main_cpp = out / "main.cpp"
    original_main = (ROOT / "test/window_dma/main.cpp").read_text()
    interval_check = ('    check(maximum_interval<=WINDOW_RESPONSE_INTERVAL &&\n'
                      '          s.response_cycles.back()-s.response_cycles[first]+1<=511*WINDOW_RESPONSE_INTERVAL+1,\n'
                      '          "hit stream exceeded the selected pipeline response interval");')
    if original_main.count(interval_check) != 1:
        raise RuntimeError("Cannot identify the standalone throughput check")
    main_cpp.write_text(original_main.replace(interval_check,
        "    // 每个周期的公开输出与参考实例相同，完成时间由 RTL 比较检查。")
        .replace("    return 0;", "    s.top.final();\n    return 0;"))
    conv = ROOT / "rtl/npu/conv"
    sources = [conv / "conv_im2col_pkg.sv", conv / "vector_engine_pkg.sv"]
    sources.extend(path for path in sorted(conv.rglob("*.sv")) if path not in sources)
    sources.extend(sorted((ROOT / "rtl/npu/dma").rglob("*.sv")))
    sources.extend([ROOT / "rtl/common/pseudo_dual_port_ram.v", ROOT / "test/window_dma/window_dma_top.sv", main_cpp])
    sources = runpy.run_path(str(ROOT / "test/monitors/sources.py"))["with_observers"](sources)
    sources = [compared if path == SOURCE else path for path in sources]
    sources.append(reference)
    hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    commands = [([args.verilator, "--cc", "--exe", "--assert", "--top-module", "window_dma_top",
                 "-Wno-fatal", "-Wno-PINMISSING", "--Mdir", str(out / "obj"), "--output-groups", "0",
                 "--output-split", "12000", "-CFLAGS", "-std=c++17", str(ROOT / "test/conv_npu/simulator.vlt"),
                 *map(str, sources)], "elaborate.log"),
                (["make", "-C", str(out / "obj"), "-f", "Vwindow_dma_top.mk", "-j", "1",
                  "OPT_FAST=-O1", "OPT_SLOW=-O0", "OPT_GLOBAL=-O1", "VK_PCH_I_FAST=", "VK_PCH_I_SLOW=",
                  "CFG_CXXFLAGS_PCH=-E"], "compile.log")]
    for command, name in commands:
        with (out / name).open("w") as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    binary = out / "obj/Vwindow_dma_top"
    trace = out / "window_cycles.csv"
    run = subprocess.run([str(binary), "+WINDOW_TRACE=" + str(out / "resident_stream.csv"),
                          "+DMA_COMPARE_TRACE=" + str(trace)],
                         cwd=ROOT, capture_output=True, text=True)
    (out / "run.log").write_text(run.stdout + run.stderr)
    run.check_returncode()
    if not all(marker in run.stdout for marker in ("WINDOW_DMA_PASS", "DMA_WINDOW_COMPARE_PASS", "WINDOW_DESCRIPTOR_COMPARE_PASS")):
        raise RuntimeError("Incomplete window comparison")
    if any(hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != before for path, before in hashes.items()):
        raise RuntimeError("Source changed during window comparison")
    report = dict(passed=True, public_outputs=output_count, reference_ref=args.reference_ref,
        source_sha256=hashlib.sha256(current.encode()).hexdigest(), input_sha256=hashes,
        reference_sha256=hashlib.sha256(original.encode()).hexdigest(),
        cycle_requirement="All public outputs and complete queue state equal to reference every cycle",
        trace_sha256=hashlib.sha256(trace.read_bytes()).hexdigest(), trace_cycles=len(trace.read_text().splitlines())-1,
        binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        log_sha256=hashlib.sha256((out / "run.log").read_bytes()).hexdigest(),
        summary=[line for line in run.stdout.splitlines() if line.startswith(
                 ("CASE ", "WINDOW_DMA_PASS", "DMA_WINDOW_COMPARE_PASS", "WINDOW_DESCRIPTOR_COMPARE_PASS"))])
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(dict(passed=True, summary=report["summary"])), flush=True)
    for path in (out / "obj").iterdir():
        if path.suffix in (".o", ".gch"):
            path.unlink()


if __name__ == "__main__":
    main()
