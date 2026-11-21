#!/usr/bin/env python3
"""检查调度器模宽减一、预测集合寄存与帧编码的严格四态结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "rtl/npu/control/ps_window_scheduler.sv"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    source_hash = digest(source)
    text = source.read_text()
    first = text.index("    assign prepare_rows_lower_nonzero[0] =")
    last = text.index("    assign prepare_part_quotient =", first)
    decrement = text[first:last]
    selection = re.search(r"    assign prediction_selection_q = .*?;", text, re.S)
    registers = re.findall(r"            prediction_(?:eligible|after_start)_q <= .*?;", text)
    active = re.search(r"            prediction_is_active_q <= (.*?);", text)
    if selection is None or len(registers) != 2 or active is None:
        raise RuntimeError("无法唯一提取预测集合逻辑")
    last = text.index("    always_ff @(posedge clk or negedge rst_n) begin\n        if (!rst_n) prediction_valid",
                      selection.start())
    encoding = text[selection.start():last]
    priority = re.search(r"\nmodule ps_scheduler_priority\b.*?\nendmodule", text, re.S)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reports = []
    for width, frames in ((1, 1), (2, 3), (5, 4), (10, 16), (11, 17), (32, 16), (33, 33)):
        id_width = max(1, (frames - 1).bit_length())
        folder = out / f"w{width}_f{frames}"
        folder.mkdir(exist_ok=True)
        model = folder / "model.sv"
        model.write_text(f"""module current_model(
    input logic clk, prediction_request,
    input logic [{width-1}:0] prepare_rows_extended,
    input logic [{frames-1}:0] prediction_eligible, prediction_after_start,
    input logic [{id_width-1}:0] active_id,
    output logic [{width-1}:0] prepare_rows_last,
    output wire [{frames-1}:0] prediction_selection_q,
    output logic [{id_width-1}:0] prediction_frame,
    output wire active_match
);
    localparam PART_MATH_W={width}, FRAME_COUNT={frames}, ID_W={id_width};
    logic [PART_MATH_W-1:0] prepare_rows_last_binary, prepare_rows_lower_nonzero;
    logic [{frames-1}:0] prediction_eligible_q, prediction_after_start_q;
    logic [FRAME_COUNT-1:0] prediction_first;
    logic [ID_W-1:0] prediction_eligible_frame, prediction_after_frame;
    logic prediction_eligible_is_active, prediction_after_is_active, prediction_is_active;
""" + decrement + encoding + "\n    assign active_match = " + active[1] + ";\n" +
            "    always_ff @(posedge clk) begin\n        if (prediction_request) begin\n" +
            "\n".join(registers) + "\n        end\n    end\nendmodule\n" +
            (priority[0] + "\n" if priority is not None else ""))
        tb = folder / "tb.sv"
        tb.write_text(f"""module tb;
    localparam W={width}, F={frames}, ID_W={id_width};
    logic clk=0, request;
    logic [W-1:0] value;
    logic [F-1:0] eligible, after_start, expected_selection;
    logic [ID_W-1:0] active_id, expected_frame;
    wire [W-1:0] actual_last;
    wire [F-1:0] actual_selection;
    wire [F-1:0] expected_first;
    wire [ID_W-1:0] actual_frame;
    wire actual_active;
    integer checks=0;
    current_model u_current(clk,request,value,eligible,after_start,active_id,
                            actual_last,actual_selection,actual_frame,actual_active);
    for(genvar frame=0;frame<F;frame++)begin
        if(frame==0)assign expected_first[frame]=expected_selection[frame];
        else assign expected_first[frame]=expected_selection[frame] && !(|expected_selection[frame-1:0]);
    end
    always_comb begin
        expected_frame='0;
        for(integer frame=0;frame<F;frame++)
            expected_frame |= ID_W'(frame) & {{ID_W{{expected_first[frame]}}}};
    end
    always @(posedge clk) begin
        if(request) expected_selection <= (|after_start) ? after_start : eligible;
    end
    task automatic compare;
        #1;
        if(actual_last !== (value-W'(1)))
            $fatal(1,"Decrement differs width=%0d value=%h actual=%h",W,value,actual_last);
        clk=1;
        #1;
        if(actual_selection !== expected_selection)
            $fatal(1,"Prediction differs frames=%0d actual=%h expected=%h",F,actual_selection,expected_selection);
        if(actual_frame !== expected_frame || actual_active !== (expected_frame==active_id))
            $fatal(1,"Prediction encoding differs frames=%0d actual=%h expected=%h",F,actual_frame,expected_frame);
        clk=0;
        checks++;
    endtask
    initial begin
        for(integer sample_i=0;sample_i<4096;sample_i++) begin
            value=W'({{$urandom,$urandom}});
            eligible=F'({{$urandom,$urandom}});
            after_start=F'({{$urandom,$urandom}});
            active_id=ID_W'($urandom);
            if(sample_i%8==0)after_start='0;
            if(sample_i%8==1)eligible='0;
            request=$urandom;
            if(sample_i>=1024) begin
                case(sample_i%4)
                    0:value[sample_i%W]=1'bx;
                    1:value[sample_i%W]=1'bz;
                    2:eligible[sample_i%F]=1'bx;
                    3:after_start[sample_i%F]=1'bz;
                endcase
                if(sample_i%16==0)request=1'bx;
                if(sample_i%16==1)request=1'bz;
                if(sample_i%16==2)active_id[sample_i%ID_W]=1'bx;
                if(sample_i%16==3)active_id[sample_i%ID_W]=1'bz;
            end
            compare();
        end
        for(integer pattern=0;pattern<4;pattern++) begin
            value={{W{{pattern[0]}}}};
            eligible={{F{{pattern[0]}}}};
            after_start={{F{{pattern[1]}}}};
            request=1'b1;
            active_id='0;
            compare();
            for(integer bit_i=0;bit_i<W;bit_i++) begin
                value[bit_i]=1'bx;compare();
                value[bit_i]=1'bz;compare();
                value[bit_i]=pattern[0];
            end
        end
        $display("SCHEDULER_FOUR_STATE_PASS checks=%0d",checks);
        $finish;
    end
endmodule
""")
        binary = folder / "test.vvp"
        with (folder / "build.log").open("w") as stream:
            subprocess.run(["iverilog", "-g2012", "-s", "tb", "-o", str(binary),
                            str(model), str(tb)], check=True, stdout=stream,
                           stderr=subprocess.STDOUT, timeout=60)
        result = subprocess.run(["vvp", str(binary)], capture_output=True, text=True, timeout=60)
        (folder / "run.log").write_text(result.stdout + result.stderr)
        match = re.search(r"SCHEDULER_FOUR_STATE_PASS checks=(\d+)", result.stdout)
        if result.returncode or match is None:
            raise RuntimeError(f"四态检查未通过：{folder / 'run.log'}")
        reports.append({"width": width, "frames": frames, "passed": True,
                        "checks": int(match[1]), "model_sha256": digest(model),
                        "test_sha256": digest(tb), "log_sha256": digest(folder / "run.log")})
    if source_hash != digest(source):
        raise RuntimeError("检查期间调度器源文件发生变化")
    report = {"passed": True, "strict_four_state": True, "source_sha256": source_hash,
              "profiles": reports, "checks": sum(row["checks"] for row in reports)}
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": True, "profiles": len(reports), "checks": report["checks"]}))


if __name__ == "__main__":
    main()
