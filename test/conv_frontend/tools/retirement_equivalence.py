#!/usr/bin/env python3
"""证明窗口替换位置的全部输入，并检查其余前端源码保持一致。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
SOURCE = "rtl/npu/conv/conv_im2col_frontend.sv"
BEGIN = "  // 请求先选择输入行，再共用计算；预取的两个阶段各自保留独立结果。\n"
END = "  // 位置解码使用已接受的描述符，快速请求的资格条件保证输入位置与保存位置相同。\n"


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-ref",default="781deda2")
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--synthesize",action="store_true")
    args=parser.parse_args()
    out=args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    current=(ROOT/SOURCE).read_text()
    reference=subprocess.check_output(["git","show",args.reference_ref+":"+SOURCE],cwd=ROOT,text=True)
    function=re.search(r"  function automatic logic \[31:0\] window_retirement\(.*?  endfunction\n",reference,re.S).group(0)
    body=current[current.index(BEGIN):current.index(END)]
    normalized=current.replace(body,function)
    normalized=normalized.replace("  logic [31:0] req_index, req_epoch, request_retire;\n"
        "  logic [2:0][15:0] retirement_row;\n  logic [2:0][31:0] retirement_value;",
        "  logic [31:0] req_index, req_epoch, req_retire_current;")
    normalized=normalized.replace(".req_window_retire(request_retire),",
        ".req_window_retire(request_pending ? window_retirement(request_y_q) : req_retire_current),")
    normalized=normalized.replace("    pf_step=pf_step_q;", "    req_retire_current=window_retirement(iy[15:0]);\n    pf_step=pf_step_q;")
    normalized=normalized.replace("    // Two ways retain the active and following channel fragments when each",
        "    pfa_retire=window_retirement(pfa_y[15:0]);\n    pf_retire=window_retirement(pf0_y[15:0]);\n"
        "    // Two ways retain the active and following channel fragments when each")
    if normalized!=reference:
        raise RuntimeError("Frontend source contains changes outside retirement arithmetic")
    miter=out/"miter.sv"
    miter.write_text(f"""module retirement_proof (
 input conv_im2col_pkg::conv_cfg_t c,
 input logic [15:0] request_y_q,
 input logic [34:0] iy, pfa_y, pf0_y,
 input logic request_pending, retire_enabled_q, short_pixel_q,
 input logic [3:0] retire_shift_q,
 input logic [15:0] retire_last_row_q,
 output logic equivalent
);
logic [2:0][15:0] retirement_row;
logic [2:0][31:0] retirement_value;
logic [31:0] request_retire,pfa_retire,pf_retire;
{function}
{body}
assign equivalent=(request_retire==(request_pending ? window_retirement(request_y_q) : window_retirement(iy[15:0]))) &&
    pfa_retire==window_retirement(pfa_y[15:0]) && pf_retire==window_retirement(pf0_y[15:0]);
endmodule
""")
    script=out/"proof.ys"
    script.write_text("read_slang --top retirement_proof "+shlex.quote(str(ROOT/"rtl/npu/conv/conv_im2col_pkg.sv"))+" "+
                      shlex.quote(str(miter))+"\nprep -top retirement_proof -flatten\n"
                      "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
    log_path=out/"formal.log"
    with log_path.open("w") as log:
        run=subprocess.run([sys.executable,str(ROOT/"scripts/fpga/open_fpga_synth.py"),"--worker",str(script)],
                           stdout=log,stderr=subprocess.STDOUT,cwd=ROOT)
    passed=run.returncode==0 and "SAT proof finished - no model found: SUCCESS!" in log_path.read_text()
    report={"reference_ref":args.reference_ref,"passed":passed,"inputs_constrained":False,
            "remaining_module_body_identical":True,"observed_bits":96,
            "source_sha256":hashlib.sha256(current.encode()).hexdigest(),
            "reference_sha256":hashlib.sha256(reference.encode()).hexdigest(),
            "miter_sha256":hashlib.sha256(miter.read_bytes()).hexdigest(),
            "log_sha256":hashlib.sha256(log_path.read_bytes()).hexdigest()}
    (out/"summary.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report),flush=True)
    if not passed:
        raise SystemExit(1)
    if args.synthesize:
        ports="""(
 input conv_im2col_pkg::conv_cfg_t c,
 input logic [15:0] request_y_q,
 input logic [34:0] iy,pfa_y,pf0_y,
 input logic request_pending,retire_enabled_q,short_pixel_q,
 input logic [3:0] retire_shift_q,
 input logic [15:0] retire_last_row_q,
 output logic [31:0] request_retire,pfa_retire,pf_retire
);\n"""
        reference_calc=out/"reference_calculation.sv"
        current_calc=out/"current_calculation.sv"
        reference_calc.write_text("module retirement_reference "+ports+function+"""
assign request_retire=request_pending ? window_retirement(request_y_q) : window_retirement(iy[15:0]);
assign pfa_retire=window_retirement(pfa_y[15:0]);
assign pf_retire=window_retirement(pf0_y[15:0]);
endmodule
""")
        current_calc.write_text("module retirement_current "+ports+"""logic [2:0][15:0] retirement_row;
logic [2:0][31:0] retirement_value;
"""+body+"endmodule\n")
        cases={name:{"top":"retirement_"+name,"sources":[
            str(ROOT/"rtl/npu/conv/conv_im2col_pkg.sv"),str(path)],
            "options":[],"configuration":{}} for name,path in
            (("reference",reference_calc),("current",current_calc))}
        cases_path=out/"calculation_cases.json"
        cases_path.write_text(json.dumps(cases,indent=2)+"\n")
        subprocess.run([sys.executable,str(ROOT/"scripts/fpga/open_fpga_synth.py"),
            "--case-config",str(cases_path),"--cases","reference","current",
            "--out",str(out/"calculation_synthesis")],cwd=ROOT,check=True)


if __name__=="__main__":
    main()
