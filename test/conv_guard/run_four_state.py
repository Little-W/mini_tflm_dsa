#!/usr/bin/env python3
"""比较读取保护器的完整四态输出，覆盖配置、握手、复位和边界地址。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test"))
from rtl_reference import read_rtl_source
SOURCE = "rtl/npu/conv/conv_axi_read_guard.sv"

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--reference-ref",default="415a70a")
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    source=(ROOT/SOURCE).read_text()
    reference=read_rtl_source(f"{args.reference_ref}:{SOURCE}",cwd=ROOT,text=True)
    paths=[]
    for label,text in [("current",source),("reference",reference)]:
        if label=="reference":text=text.replace("module conv_axi_read_guard", "module reference_conv_axi_read_guard")
        # Icarus 使用同宽逻辑类型表示枚举；常量编码和所有表达式保持不变。
        text=re.sub(r"typedef enum logic \[2:0\] \{([^}]+)\} state_t;",
                    lambda m:"typedef logic [2:0] state_t;\n"+"\n".join(f"localparam logic [2:0] {n.strip()}=3'd{i};" for i,n in enumerate(m[1].split(","))),text)
        path=out/f"{label}.sv";path.write_text(text);paths.append(path)
    bench=(ROOT/"test/conv_guard/tb_guard_compare.sv").read_text()
    bench=bench.replace("  for (genvar width_index", """  function automatic logic unknown_bit(input logic [3:0] value);
    case(value)
      4'd0: unknown_bit=1'bx;
      4'd1: unknown_bit=1'bz;
      default: unknown_bit=value[0];
    endcase
  endfunction
  for (genvar width_index""")
    bench=bench.replace("cycle<50000", "cycle<20000")
    marker="      @(posedge clk); #2;"
    injection="""      if (cycle%3==0) begin
        for (int bit_i=0;bit_i<32;bit_i++) begin
          word=random_word(); s_araddr[bit_i]=unknown_bit(word[3:0]);
          for (int allocation=0;allocation<4;allocation++) begin
            word=random_word();cfg_base[allocation][bit_i]=unknown_bit(word[3:0]);
            word=random_word();cfg_end[allocation][bit_i]=unknown_bit(word[3:0]);
          end
        end
        word=random_word(); s_arvalid=unknown_bit(word[3:0]);
        m_arready=unknown_bit(word[7:4]);s_rready=unknown_bit(word[11:8]);
        cfg_valid=unknown_bit(word[15:12]);m_rvalid=unknown_bit(word[19:16]);
        m_rlast=unknown_bit(word[23:20]);enable=unknown_bit(word[27:24]);
        if (cycle%17==0) rst_n=unknown_bit(word[31:28]);
        for(int bit_i=0;bit_i<8;bit_i++) begin
          word=random_word();s_arlen[bit_i]=unknown_bit(word[3:0]);
        end
      end
"""
    assert bench.count(marker)==1
    bench=bench.replace(marker,injection+marker)
    # 额外比较仲裁输出与全部保存状态。
    marker='        if (rst_n) begin'
    extra="""        if ({u_current.o_arb_arvalid,u_current.state,u_current.addr_q,u_current.len_q,
             u_current.beat_q,u_current.pending_mask,u_current.error_q,u_current.word_q,
             u_current.direct_outstanding} !==
            {u_reference.o_arb_arvalid,u_reference.state,u_reference.addr_q,u_reference.len_q,
             u_reference.beat_q,u_reference.pending_mask,u_reference.error_q,u_reference.word_q,
             u_reference.direct_outstanding})
          $fatal(1,"guard state mismatch width=%0d split=%0d cycle=%0d",DATA_W,split,compared_cycles);
"""
    assert bench.count(marker)==1;bench=bench.replace(marker,extra+marker)
    tb=out/"tb.sv";tb.write_text(bench);binary=out/"simulation"
    with (out/"build.log").open("w") as f:
        subprocess.run(["iverilog","-g2012","-s","tb_guard_compare","-o",str(binary),*map(str,paths),str(tb)],stdout=f,stderr=subprocess.STDOUT,check=True)
    with (out/"run.log").open("w") as f:
        subprocess.run(["vvp",str(binary)],stdout=f,stderr=subprocess.STDOUT,check=True,timeout=120)
    output=(out/"run.log").read_text()
    assert "GUARD_COMPARE_PASS cycles=20000 configurations=4" in output
    assert output.count("GUARD_COMPARE_CASE_PASS")==4
    assert source==(ROOT/SOURCE).read_text()
    result={"passed":True,"source_sha256":hashlib.sha256(source.encode()).hexdigest(),
            "reference_sha256":hashlib.sha256(reference.encode()).hexdigest(),
            "test_sha256":digest(Path(__file__)),"testbench_sha256":digest(tb),"log_sha256":digest(out/"run.log"),
            "cycles":20000,"configurations":4,"strict_four_state":True,
            "simulation_type_conversion":"same-width logic state and identical enumeration values"}
    (out/"summary.json").write_text(json.dumps(result,indent=2)+"\n")
    print(output)
if __name__=="__main__":main()
