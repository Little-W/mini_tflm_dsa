#!/usr/bin/env python3
"""从偏置缓冲区提取实际读取使能表达式，验证分支选择与四态写入资格。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/npu/loaders/bias_loader_buffer.sv"
FIELDS = (("read_enable", 1), ("storage_i_wr_en", 1), ("is_mode", 1),
          ("group_read_start", 1), ("ws_read_start", 1), ("collision_equal", 4),
          ("write_address", 9), ("read_address", 9), ("storage_i_wr_mask", 8))
WIDTH = sum(width for _, width in FIELDS)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(text, label):
    marker = "  always_comb begin\n    case (^{is_mode, group_read_start, ws_read_start})"
    start = text.index(marker)
    body = text[start:text.index("  assign storage_i_rd_addr", start)]
    declarations, assignments, offset = [], [], 0
    for name, width in FIELDS:
        declarations.append(f"wire [{width-1}:0] {name};")
        assignments.append(f"assign {name}=values[{offset}+:{width}];")
        offset += width
    return f"""// 用自由输入表示碰撞结果和实际写入资格，保留原有条件语句。
module {label}(input wire [{WIDTH-1}:0] values, output wire [2:0] observed);
localparam RAM_ADDR_W=9,BANK_ADDR_W=8,RAM_BYTES=8;
logic collision_selected,collision_other,collision_scalar_selected;
logic storage_write_accepted,storage_i_rd_en,storage_read_selected;
"""+"\n".join(declarations+assignments)+"\nwire [8:0] storage_i_wr_addr=write_address;\n"+body+"""
assign observed={collision_selected,storage_write_accepted,storage_i_rd_en};
endmodule
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference", default="f7f90963")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    actual = root / SOURCE
    reference = subprocess.check_output(["git", "show", args.reference+":"+SOURCE], cwd=ROOT, text=True)
    model = out / "control.sv"
    model.write_text(extract(reference, "reference_enable")+extract(actual.read_text(), "current_enable")+f"""
// 比较实际分支选择、写入接受和同步读取使能。
module proof(input wire [{WIDTH-1}:0] values,output wire equivalent);
wire [2:0] expected,actual;
reference_enable u_reference(values,expected);
current_enable u_current(values,actual);
assign equivalent=actual==expected;
endmodule
""")
    resolve = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]
    sources = resolve([model], root)
    hashes = {str(path): digest(path) for path in [actual, *sources]}
    bench = out / "four_state.sv"
    bench.write_text(f"""// 检查全部模式控制的四态组合以及任意写入掩码和地址。
module tb;
reg [{WIDTH-1}:0] values,known;
wire [2:0] expected,actual;
integer seed=32'h21854e3c,checks=0,choice;
reference_enable u_reference(values,expected);
current_enable u_current(values,actual);
task check;
 begin #1;checks++;
  if(actual!==expected)$fatal(1,"Read qualification differs: values=%h expected=%h actual=%h",values,expected,actual);
 end
endtask
initial begin
 for(integer sample=0;sample<65536;sample++)begin
  for(integer bit_index=0;bit_index<{WIDTH};bit_index++)begin
   choice=bit_index<5 ? ((sample>>(2*bit_index))&3) :
    sample<32768 ? int'($unsigned($random(seed))%2) : int'($unsigned($random(seed))%4);
   case(choice)0:values[bit_index]=0;1:values[bit_index]=1;2:values[bit_index]=1'bx;3:values[bit_index]=1'bz;endcase
  end
  check();
 end
 for(integer sample=0;sample<256;sample++)begin
  for(integer bit_index=0;bit_index<{WIDTH};bit_index++)known[bit_index]=$random(seed);
  for(integer bit_index=0;bit_index<{WIDTH};bit_index++)begin
   values=known;values[bit_index]=1'bx;check();values=known;values[bit_index]=1'bz;check();
  end
 end
 values='x;check();values='z;check();
 $display("BIAS_READ_ENABLE_PASS checks=%0d",checks);$finish;
end
endmodule
""")
    runs = []

    def execute(command, log):
        with log.open("w") as stream:
            subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                           timeout=300, check=True)

    for synthesis in (False, True):
        name = "fpga" if synthesis else "generic"
        defines = ["-DSYNTHESIS=1", "-DXILINX_FPGA=1"] if synthesis else []
        slang = defines if synthesis else ["-USYNTHESIS", "-UXILINX_FPGA"]
        script, log = out / (name+".ys"), out / (name+"_formal.log")
        script.write_text("read_slang --top proof "+shlex.join(slang+list(map(str, sources)))+
            "\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\nprep -top proof -flatten\nopt -full\nsat -verify -prove equivalent 1\n")
        execute([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)], log)
        binary, simulation = out / (name+".vvp"), out / (name+"_four_state.log")
        execute(["iverilog", "-g2012", "-s", "tb", *defines, "-o", str(binary),
                 *map(str, sources), str(bench)], out / (name+"_compile.log"))
        execute(["vvp", str(binary)], simulation)
        match = re.search(r"BIAS_READ_ENABLE_PASS checks=(\d+)", simulation.read_text())
        assert match
        binary.unlink()
        runs.append(dict(synthesis=synthesis, slang_definitions=slang, passed=True,
                         formal_log_sha256=digest(log), four_state_comparisons=int(match[1]),
                         four_state_log_sha256=digest(simulation)))
        print(name, "PASS", match[1], flush=True)
    assert hashes == {str(path): digest(path) for path in [actual, *sources]}
    (out / "summary.json").write_text(json.dumps(dict(passed=True, reference=args.reference,
        source_sha256=hashes, input_constraints=[], profiles=runs, test_sha256=digest(Path(__file__))),
        ensure_ascii=False, indent=2)+"\n")


if __name__ == "__main__":
    main()
