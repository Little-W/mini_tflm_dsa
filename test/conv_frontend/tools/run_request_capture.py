#!/usr/bin/env python3
"""Run numerical frontend transactions with registered cache requests."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3]


def run(command,log):
    with log.open("w")as handle:
        subprocess.run(list(map(str,command)),stdout=handle,stderr=subprocess.STDOUT,check=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root",type=Path,default=ROOT)
    parser.add_argument("--harness-root",type=Path,default=ROOT)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--verilator",default="verilator")
    parser.add_argument("--lanes",type=int,choices=(8,16),nargs="+",default=[8,16])
    parser.add_argument("--registered",type=int,choices=(0,1),default=1)
    parser.add_argument("--windows",type=int,choices=(0,1),nargs="+",default=[0,1])
    args=parser.parse_args();root=args.source_root.resolve();harness=args.harness_root.resolve()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    test=harness/"test/conv_frontend";helper=runpy.run_path(str(test/"tools/compare_frontend.py"))
    files=runpy.run_path(str(test/"tools/run_rtl.py"))["FILES"]
    common=[]
    monitors=out/"monitors";monitors.mkdir(exist_ok=True)
    for path in map(Path,files):
        relative=path.relative_to(harness)
        if relative.parts[0]=="rtl":common.append(root/relative)
        elif relative.parts[:2]==("test","monitors"):
            target=monitors/path.name
            target.write_text("`undef SYNTHESIS\n"+path.read_text()+"\n`define SYNTHESIS 1\n")
            common.append(target)
        elif path.name!="tb_conv_im2col_frontend.sv":common.append(path)
    text=helper["widen_memory"]((test/"tests/tb_conv_im2col_frontend.sv").read_text())
    text,count=re.subn(r"conv_im2col_frontend\s+#\(",
        f"conv_im2col_frontend #(.REGISTER_CACHE_REQUEST(1'b{args.registered}),.REGISTER_DESCRIPTOR(1'b0),.CACHE_RESPONSE_DEPTH(1),",text)
    if count!=1:raise RuntimeError(("frontend instances",count))
    monitor='''
 integer incoming_captures=0,fast_saved_word_hits=0,request_stalls=0;
 logic check_saved_word_state=0;
 always @(posedge clk) begin
  check_saved_word_state<=0;
  if(rst_n)begin
   if(g_direct.dut.cache_req_valid&&g_direct.dut.cache_req_ready&&g_direct.dut.incoming_context)
    incoming_captures++;
   if(g_direct.dut.request_pending&&!g_direct.dut.cache_port_ready)request_stalls++;
   if(g_direct.dut.tile_commit&&!g_direct.dut.committing_tile.invalid&&
      g_direct.dut.committing_tile.fast&&!g_direct.dut.committing_tile.padding&&
      g_direct.dut.committing_tile.word_hit)begin
    fast_saved_word_hits++;
    check_saved_word_state<=1;
   end
  end
 end
 always @(negedge clk)begin
  if(rst_n&&check_saved_word_state)
   assert(g_direct.dut.state[$clog2(conv_im2col_frontend_pkg::STREAM)])
    else $fatal(1,"Saved-word descriptor did not enter STREAM");
 end
 final $display("REQUEST_CAPTURE_PASS incoming=%0d saved_word_hits=%0d stalls=%0d",
                incoming_captures,fast_saved_word_hits,request_stalls);
'''
    point=text.rindex("endmodule");text=text[:point]+monitor+text[point:]
    bench=out/"tb_request_capture.sv";bench.write_text(text)
    vectors=out/"vectors.txt"
    run([sys.executable,test/"tests/gen_rtl_vectors.py","--size","16","--out",vectors],out/"vectors.log")
    rows=[]
    for lanes in args.lanes:
        sets=16 if lanes==8 else 64
        for window in args.windows:
            case=out/f"lanes{lanes}_window{window}";case.mkdir(exist_ok=True)
            sources=[*common,bench]
            hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in sources}
            command=[args.verilator,"--binary","--timing","--assert","-DNPU_SIM_ASSERT","-DCONV_ASSERT",
                "-DXILINX_FPGA=1","-DSYNTHESIS=1","-Wno-fatal","--top-module","tb_conv_im2col_frontend",
                "-GSIZE=16","-GBUS_WIDTH=64",f"-GLANES={lanes}",f"-GCACHE_SETS={sets}","-GLINE_BYTES=128",
                "-GNARROW_MODE=2",f"-GWINDOWED=1'b{window}",f"-GPREFETCH=1'b{window}",
                "--Mdir",case/"obj","-j","2","--output-groups","0","--output-split","12000",
                "-CFLAGS","-std=c++20 -O1","-MAKEFLAGS","OPT_FAST=-O1 OPT_SLOW=-O0 VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E",
                "-I"+str(root/"include"),*sources]
            run(command,case/"build.log")
            warnings=helper["reviewed_warnings"](case/"build.log",0)
            run([case/"obj/Vtb_conv_im2col_frontend","+VECTORS="+str(vectors)],case/"run.log")
            result=(case/"run.log").read_text()
            match=re.search(r"RTL_FRONTEND_PASS jobs=(\d+) cycles=(\d+)",result)
            capture=re.search(r"REQUEST_CAPTURE_PASS incoming=(\d+) saved_word_hits=(\d+) stalls=(\d+)",result)
            if match is None or capture is None:raise RuntimeError(str(case/"run.log"))
            if hashes!={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in sources}:raise RuntimeError("Source changed during verification")
            rows.append({"lanes":lanes,"sets":sets,"line_bytes":128,"windowed_prefetch":window,
                "jobs":int(match[1]),"cycles":int(match[2]),"incoming_captures":int(capture[1]),
                "saved_word_hits":int(capture[2]),"request_stalls":int(capture[3]),"passed":True,
                "source_sha256":hashes,"warnings":warnings})
            for temporary in (case/"obj").iterdir():
                if temporary.suffix in (".o",".a",".gch",".cpp",".h",".d",".mk"):
                    temporary.unlink()
            print("REQUEST_CAPTURE_NUMERIC_PASS",lanes,window,match.groups(),capture.groups(),flush=True)
    (out/"summary.json").write_text(json.dumps({"passed":True,"registered_requests":args.registered,"cases":rows},indent=2)+"\n")


if __name__=="__main__":main()
