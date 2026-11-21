#!/usr/bin/env python3
"""证明 FIFO 每字节有效掩码的完整组合表达式，并检查四态输入。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

from run_formal import ROOT, SOURCE, read_rtl_source


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def model(source: str, label: str) -> str:
    body = source[:source.index("module vec_s8_to_fifo_linear")]
    start = body.index("    valid_cols_i = int'(output_col_count);")
    arithmetic = body[start:body.index("\n\n    if (select_coalesce || stream_active)", start)]
    start = body.index("      if (select_coalesce) begin\n        output_mask = '1;")
    mask = body[start:body.index("\n    end\n  end\n", start)]
    return f"""module {label}_mask #(
    parameter VLEN=16,BUS_WIDTH=64,
    parameter COUNT_WIDTH=$clog2(VLEN+1),
    parameter ROW_BEATS=(VLEN+BUS_WIDTH/8-1)/(BUS_WIDTH/8),
    parameter BEAT_WIDTH=(ROW_BEATS<=1)?1:$clog2(ROW_BEATS)
)(
    input logic [COUNT_WIDTH-1:0] output_col_count,
    input logic [BEAT_WIDTH-1:0] beat_idx,
    input logic select_coalesce,stream_active,
    output logic [BUS_WIDTH/8-1:0] output_mask
);
    localparam BYTE_PER_BEAT=BUS_WIDTH/8;
    integer valid_cols_i,beat_col_start_i,valid_in_beat_i;
    always_comb begin
        output_mask='0;
{arithmetic}
        if(select_coalesce||stream_active) begin
{mask}
        end
    end
endmodule
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference", default="cedf4ed33661a53c8194eca1d484cdc2279d7549")
    parser.add_argument("--reference-file", type=Path)
    parser.add_argument("--iverilog", default="iverilog")
    parser.add_argument("--vvp", default="vvp")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_path = args.source_root / SOURCE
    source = source_path.read_text()
    reference = (args.reference_file.read_text() if args.reference_file else
                 read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT, text=True))
    models = []
    for label, text in (("reference", reference), ("current", source)):
        path = out / f"{label}.sv"
        path.write_text(model(text, label))
        models.append(path)
    profiles = [(2,8),(2,64),(7,32),(8,32),(8,64),(16,32),(16,64),
                (16,128),(17,64),(32,32),(32,64),(64,256)]
    report = dict(source_sha256=digest(source_path),
                  reference_sha256=hashlib.sha256(reference.encode()).hexdigest(),
                  inputs_constrained=False, runs=[])
    for vlen,bus in profiles:
        folder = out / f"v{vlen}_b{bus}"
        folder.mkdir(exist_ok=True)
        commands = []
        for label, path in zip(("reference","current"),models):
            commands += [f"read_slang --top {label}_mask -GVLEN={vlen} -GBUS_WIDTH={bus} " + shlex.quote(str(path)),
                         f"prep -top {label}_mask", f"design -stash {label}"]
        commands += ["design -copy-from reference -as reference reference_mask",
                     "design -copy-from current -as current current_mask",
                     "miter -equiv -flatten reference current miter", "hierarchy -top miter",
                     "sat -prove trigger 0 -verify"]
        script,log = folder / "run.ys",folder / "formal.log"
        script.write_text("\n".join(commands)+"\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable,str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker",str(script)],stdout=stream,stderr=subprocess.STDOUT,
                           check=True,timeout=60)
        if "SUCCESS!" not in log.read_text():
            raise RuntimeError("掩码组合证明未完成")
        report["runs"].append(dict(vlen=vlen,bus_width=bus,passed=True,log_sha256=digest(log)))
    bench = """module mask_pair #(parameter VLEN=16,BUS_WIDTH=64)(
    input logic [15:0] values,input logic [1:0] controls,output wire o_equal
);
    localparam CW=$clog2(VLEN+1),RB=(VLEN+BUS_WIDTH/8-1)/(BUS_WIDTH/8);
    localparam BW=(RB<=1)?1:$clog2(RB);
    wire [BUS_WIDTH/8-1:0] reference_value,current_value;
    reference_mask #(.VLEN(VLEN),.BUS_WIDTH(BUS_WIDTH)) u_reference(
        .output_col_count(values[0+:CW]),.beat_idx(values[8+:BW]),
        .select_coalesce(controls[0]),.stream_active(controls[1]),.output_mask(reference_value));
    current_mask #(.VLEN(VLEN),.BUS_WIDTH(BUS_WIDTH)) u_current(
        .output_col_count(values[0+:CW]),.beat_idx(values[8+:BW]),
        .select_coalesce(controls[0]),.stream_active(controls[1]),.output_mask(current_value));
    assign o_equal=reference_value===current_value;
endmodule
module tb;
    logic [15:0] values=0;
    logic [1:0] controls=0;
    logic [31:0] random_state=32'h78ab6159;
    integer sample_index,bit_index;
    function automatic logic symbol(input logic [3:0] value);
        case(value)
            4'd0:symbol=1'bx;
            4'd1:symbol=1'bz;
            default:symbol=value[0];
        endcase
    endfunction
    task automatic advance_random;
        random_state=random_state^(random_state<<13);
        random_state=random_state^(random_state>>17);
        random_state=random_state^(random_state<<5);
    endtask
"""
    for index,(vlen,bus) in enumerate(profiles):
        bench += f"""
    wire equal_{index};
    mask_pair #(.VLEN({vlen}),.BUS_WIDTH({bus})) u_pair_{index}(.values,.controls,.o_equal(equal_{index}));
"""
    bench += """
    initial begin
        for(sample_index=0;sample_index<65536;sample_index=sample_index+1) begin
            for(bit_index=0;bit_index<16;bit_index=bit_index+1) begin
                advance_random();values[bit_index]=symbol(random_state[3:0]);
            end
            for(bit_index=0;bit_index<2;bit_index=bit_index+1) begin
                advance_random();controls[bit_index]=symbol(random_state[3:0]);
            end
            #1;
"""
    for index in range(len(profiles)):
        bench += f'            if(equal_{index}!==1\'b1) $fatal(1,"FIFO mask mismatch profile={index} sample=%0d",sample_index);\n'
    bench += """
        end
        $display("FIFO_MASK_FOUR_STATE_PASS samples=65536 profiles=12 comparisons=786432");
        $finish;
    end
endmodule
"""
    testbench = out / "tb.sv"
    testbench.write_text(bench)
    binary = out / "simulation"
    with (out / "compile.log").open("w") as stream:
        subprocess.run([args.iverilog,"-g2012","-s","tb","-o",str(binary),
                        *map(str,models),str(testbench)],stdout=stream,stderr=subprocess.STDOUT,check=True)
    result = subprocess.run([args.vvp,str(binary)],capture_output=True,text=True,timeout=180)
    (out / "run.log").write_text(result.stdout+result.stderr)
    result.check_returncode()
    if "FIFO_MASK_FOUR_STATE_PASS" not in result.stdout:
        raise RuntimeError("掩码四态检查未完成")
    if source != source_path.read_text():
        raise RuntimeError("验证期间源码发生变化")
    report.update(passed=True,four_state_comparisons=786432,samples=65536,
                  model_sha256={p.name:digest(p) for p in models},
                  testbench_sha256=digest(testbench),log_sha256=digest(out / "run.log"))
    (out / "summary.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
