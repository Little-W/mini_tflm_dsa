#!/usr/bin/env python3
"""检查写指针在未知控制位、银行状态及复位输入下的四态行为。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from run_formal import ROOT, SOURCE, pointer_model, read_rtl_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = (ROOT / SOURCE).read_text()
    reference = read_rtl_source(f"415a70a:{SOURCE}", cwd=ROOT, text=True)
    model = out / "pointer.sv"
    model.write_text(pointer_model(source, reference))
    testbench = out / "tb.sv"
    body = """module tb;
    logic clk=0,rst_n=0,finish_write_bank=0;
    logic [63:0] bank_ready=0;
    logic [31:0] random_state=32'h5182c6a9;
    integer cycle,bit_index;
    function automatic logic symbol(input logic [2:0] value);
        case(value)
            3'd0: symbol=1'bx;
            3'd1: symbol=1'bz;
            default: symbol=value[0];
        endcase
    endfunction
    task automatic advance_random;
        random_state=random_state ^ (random_state << 13);
        random_state=random_state ^ (random_state >> 17);
        random_state=random_state ^ (random_state << 5);
    endtask
"""
    banks = (1,2,3,8,16,32,64)
    for count in banks:
        body += f"""
    pointer_formal #(.BANKS({count})) u_{count}(
        .clk,.rst_n,.finish_write_bank,.bank_ready(bank_ready[{count-1}:0]),.o_equal());
    always @(negedge clk) begin
        if (u_{count}.sampled) begin
            if (u_{count}.write_bank !== u_{count}.reference_bank ||
                u_{count}.write_bank_mask_q !== ({count}'(1) << u_{count}.write_bank) ||
                (!u_{count}.write_bank_blocked) !== (!bank_ready[u_{count}.reference_bank]) ||
                (!u_{count}.next_write_bank_blocked) !== (!bank_ready[u_{count}.next_bank(u_{count}.reference_bank)]))
                $fatal(1,"Pointer four-state mismatch banks={count} cycle=%0d",cycle);
        end
    end
"""
    body += """
    initial begin
        #1;clk=1;#1;clk=0;#1;
        for(cycle=0;cycle<20000;cycle=cycle+1) begin
            advance_random();
            rst_n=(cycle%257==0)?1'b0:((cycle%97==0)?symbol(random_state[2:0]):1'b1);
            advance_random();finish_write_bank=symbol(random_state[2:0]);
            for(bit_index=0;bit_index<64;bit_index=bit_index+1) begin
                advance_random();bank_ready[bit_index]=symbol(random_state[2:0]);
            end
            #1;clk=1;#1;clk=0;#1;
        end
        $display("FIFO_POINTER_FOUR_STATE_PASS cycles=20000 profiles=7 comparisons=560000");
        $finish;
    end
endmodule
"""
    testbench.write_text(body)
    binary = out / "simulation"
    subprocess.run(["iverilog", "-g2012", "-s", "tb", "-o", str(binary), str(model), str(testbench)], check=True)
    result = subprocess.run(["vvp", str(binary)], capture_output=True, text=True, check=True, timeout=120)
    (out / "run.log").write_text(result.stdout + result.stderr)
    if "FIFO_POINTER_FOUR_STATE_PASS" not in result.stdout:
        raise RuntimeError(result.stdout)
    report = dict(passed=True, cycles=20000, profiles=list(banks), comparisons=560000,
                  source_sha256=hashlib.sha256(source.encode()).hexdigest(),
                  model_sha256=hashlib.sha256(model.read_bytes()).hexdigest(),
                  testbench_sha256=hashlib.sha256(testbench.read_bytes()).hexdigest())
    if source != (ROOT / SOURCE).read_text():
        raise RuntimeError("验证期间源码发生变化")
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(result.stdout, end="")


if __name__ == "__main__":
    main()
