#!/usr/bin/env python3
"""验证并行比较器默认配置与保留分组配置的全部二态输入及四态语义。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "rtl/common/parallel_unsigned_compare.sv"
WIDTHS = (1, 2, 3, 7, 16, 23, 24, 27, 28, 29, 32, 35, 46, 47, 64)
SEED = 20261125


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--synthesis", action="store_true", help="检查 FPGA 的分段比较实现")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    hashes = {str(SOURCE.relative_to(ROOT)): digest(SOURCE), "verification_script": digest(__file__)}
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources = resolve([SOURCE], ROOT)
    hashes.update({str(path.relative_to(ROOT)): digest(path) for path in sources})
    definitions = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] if args.synthesis else []
    proof = out / "proof.sv"
    proof.write_text('''module proof #(parameter int unsigned p_width=32)(
    input logic [p_width-1:0] i_a,i_b,
    output logic equivalent,
    output wire [1:0] default_value, preserved_value, expected
);
parallel_unsigned_compare #(.p_width(p_width)) u_default(
    .i_a,.i_b,.o_less(default_value[1]),.o_equal(default_value[0]));
parallel_unsigned_compare #(.p_width(p_width),.p_preserve_groups(1'b1)) u_preserved(
    .i_a,.i_b,.o_less(preserved_value[1]),.o_equal(preserved_value[0]));
assign expected={i_a<i_b,i_a==i_b};
assign equivalent=(default_value===expected)&&(preserved_value===expected);
endmodule
''')
    bench = out / "tb.sv"
    bench.write_text('''module tb;
parameter int unsigned p_width=32;
logic [p_width-1:0] i_a,i_b,saved_a,saved_b;
wire [1:0] default_value,preserved_value,expected;
wire equivalent;
logic [31:0] random_state=32'd20261125;
integer checks=0;
proof #(.p_width(p_width)) dut(.*);
function automatic [31:0] random_word;
    random_state=random_state^(random_state<<13);
    random_state=random_state^(random_state>>17);
    random_state=random_state^(random_state<<5);
    return random_state;
endfunction
task check_value;
    #1;
    if(equivalent!==1'b1)
        $fatal(1,"comparison differs width=%0d a=%h b=%h default=%b preserved=%b expected=%b",
            p_width,i_a,i_b,default_value,preserved_value,expected);
    checks++;
endtask
initial begin
    for(integer sample=0;sample<2048;sample++)begin
        i_a=p_width'({random_word(),random_word()});
        i_b=p_width'({random_word(),random_word()});
        check_value();
        if(sample%8==0)begin
            i_b=i_a;check_value();
            i_b=i_a+p_width'(1);check_value();
            i_b=i_a-p_width'(1);check_value();
        end
    end
    for(integer trial=0;trial<8;trial++)begin
        saved_a=p_width'({random_word(),random_word()});
        saved_b=p_width'({random_word(),random_word()});
        if(trial==0)begin saved_a='0;saved_b='0;end
        if(trial==1)begin saved_a='1;saved_b='1;end
        for(integer bit_index=0;bit_index<2*p_width;bit_index++)begin
            {i_a,i_b}={saved_a,saved_b};
            if(bit_index<p_width)i_b[bit_index]=1'bx;
            else i_a[bit_index-p_width]=1'bx;
            check_value();
            {i_a,i_b}={saved_a,saved_b};
            if(bit_index<p_width)i_b[bit_index]=1'bz;
            else i_a[bit_index-p_width]=1'bz;
            check_value();
        end
    end
    i_a='x;i_b='x;check_value();
    i_a='z;i_b='z;check_value();
    $display("PASS width=%0d vectors=%0d",p_width,checks);
    $finish;
end
endmodule
''')
    rows = []
    for width in WIDTHS:
        script = out / f"w{width}.ys"
        log = out / f"w{width}_formal.log"
        script.write_text(shlex.join(["read_slang", "--top", "proof", f"-Gp_width={width}",
                                      *definitions, *map(str, sources), str(proof)]) + "\n" +
                          "prep -top proof -flatten\ncheck -assert\n" +
                          "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=120)
        if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError(f"Formal proof did not complete: {log}")
        binary = out / f"w{width}.vvp"
        with (out / f"w{width}_compile.log").open("w") as stream:
            subprocess.run(["iverilog", "-g2012", "-s", "tb", f"-Ptb.p_width={width}",
                            *definitions, "-o", str(binary), *map(str, sources), str(proof), str(bench)],
                           stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
        simulation = subprocess.check_output(["vvp", str(binary)], text=True, timeout=120)
        (out / f"w{width}_four_state.log").write_text(simulation)
        vectors = 2818 + 32 * width
        if f"PASS width={width} vectors={vectors}" not in simulation:
            raise RuntimeError(f"Four-state check did not complete for width {width}")
        rows.append(dict(width=width, preserve_groups=[0, 1], formal_passed=True,
                         four_state_vectors=vectors, four_state_output_comparisons=2*vectors,
                         passed=True))
        print(json.dumps(rows[-1]), flush=True)
    current_hashes = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    current_hashes["verification_script"] = digest(__file__)
    if hashes != current_hashes:
        raise RuntimeError("Sources changed during verification")
    (out / "summary.json").write_text(json.dumps(dict(passed=True, source_sha256=hashes,
        random_seed=SEED, synthesis=args.synthesis, inputs_constrained=False, cases=rows), indent=2) + "\n")


if __name__ == "__main__":
    main()
