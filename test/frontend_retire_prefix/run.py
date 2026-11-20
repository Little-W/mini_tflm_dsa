#!/usr/bin/env python3
"""证明退休行的十七位条件递增及三路完整结果保持全部输入行为。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/conv/conv_im2col_frontend.sv")
BEGIN = "  // 请求先选择输入行，再共用计算；预取的两个阶段各自保留独立结果。\n"
END = "  // 位置解码使用已接受的描述符，快速请求的资格条件保证输入位置与保存位置相同。\n"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unit(name, body):
    return "module " + name + """(
  input logic [15:0] request_y_q, pad_top, retire_last_row_q,
  input logic [34:0] iy, pfa_y, pf0_y,
  input logic request_pending, retire_enabled_q, short_pixel_q,
  input logic [3:0] retire_shift_q,
  output logic [95:0] observed
);
  typedef struct packed {logic [15:0] pad_top;} config_t;
  config_t c;
  logic [2:0][15:0] retirement_row;
  logic [2:0][31:0] retirement_value;
  logic [31:0] request_retire, pfa_retire, pf_retire;
  assign c.pad_top=pad_top;
""" + body + """
  assign observed={request_retire,pfa_retire,pf_retire};
endmodule
"""


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference",default="9c112bfe")
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    out=args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    current=(ROOT/SOURCE).read_text()
    reference=read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT, text=True)
    current_body=current[current.index(BEGIN):current.index(END)]
    reference_body=reference[reference.index(BEGIN):reference.index(END)]
    if current.replace(current_body,reference_body,1)!=reference:
        raise RuntimeError("Changes outside retirement arithmetic require verification")
    calculation_start=current_body.index("    localparam bit p_increment_use_lut")
    calculation_end=current_body.index("    assign bounded_row",calculation_start)
    calculation=current_body[calculation_start:calculation_end]
    old="    assign {unused_increment_carry, incremented_row} = {1'b0, shifted_row} + {17'd0, short_pixel_q};\n"
    if current_body.replace(calculation,old,1)!=reference_body:
        raise RuntimeError("Changes outside conditional increment require verification")
    proof=out/"retirement.sv"
    proof.write_text(unit("current_retirement",current_body)+unit("reference_retirement",reference_body)+"""
module retirement_proof(
  input logic [15:0] request_y_q, pad_top, retire_last_row_q,
  input logic [34:0] iy, pfa_y, pf0_y,
  input logic request_pending, retire_enabled_q, short_pixel_q,
  input logic [3:0] retire_shift_q,
  output logic equivalent
);
  logic [95:0] current_observed, reference_observed;
  current_retirement u_current(.*,.observed(current_observed));
  reference_retirement u_reference(.*,.observed(reference_observed));
  assign equivalent=current_observed==reference_observed;
endmodule
module increment_proof(
  input logic [16:0] shifted_row,
  input logic short_pixel_q,
  output logic equivalent
);
  logic [16:0] incremented_row;
  logic unused_increment_carry;
  logic [17:0] reference_increment;
"""+calculation+"""
  assign reference_increment={1'b0,shifted_row}+{17'd0,short_pixel_q};
  assign equivalent={unused_increment_carry,incremented_row}==reference_increment;
endmodule
""")
    import pyosys
    library=Path(pyosys.__file__).parent/"share/xilinx/cells_sim.v"
    models=[]
    for primitive in ("LUT6","LUT6_2"):
        text=re.search(r"^module "+primitive+r"\b.*?^endmodule",library.read_text(),re.M|re.S)[0]
        models.append(re.sub(r"\bspecify\b.*?\bendspecify\b","",text,flags=re.S))
    primitive_file=out/"xilinx_primitives.sv"
    primitive_file.write_text("\n".join(models)+"\n")
    cases=[]
    for mode in ("generic","fpga"):
        for top,inputs,outputs in (("increment_proof",18,18),("retirement_proof",160,96)):
            name=mode+"_"+top
            script,log_path=out/(name+".ys"),out/(name+".log")
            defines=("-D XILINX_FPGA -D SYNTHESIS -D YOSYS -D VERIFIC " if mode=="fpga" else "-D ASIC_SYNTHESIS ")
            sources=[proof]+([primitive_file] if mode=="fpga" else [])
            script.write_text("read_slang --top "+top+" "+defines+" ".join(shlex.quote(str(p)) for p in sources)+
                "\nprep -top "+top+" -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
            with log_path.open("w") as log:
                subprocess.run([sys.executable,str(ROOT/"scripts/fpga/open_fpga_synth.py"),"--worker",str(script)],
                    cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
            if "SAT proof finished - no model found: SUCCESS!" not in log_path.read_text():
                raise RuntimeError("Retirement proof incomplete: "+name)
            cases.append(dict(mode=mode,top=top,passed=True,input_bits=inputs,observed_bits=outputs,
                script_sha256=digest(script.read_bytes()),log_sha256=digest(log_path.read_bytes())))
    result=dict(passed=True,reference_ref=args.reference,
        reference_commit=subprocess.check_output(["git","rev-parse",args.reference],cwd=ROOT,text=True).strip(),
        source_sha256=digest(current.encode()),reference_sha256=digest(reference.encode()),
        unchanged_outside_conditional_increment=True,actual_source_expressions=True,inputs_constrained=False,
        proof_sha256=digest(proof.read_bytes()),primitive_library_sha256=digest(library.read_bytes()),
        primitive_model_sha256=digest(primitive_file.read_bytes()),cases=cases)
    (out/"summary.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result),flush=True)


if __name__=="__main__":
    main()
