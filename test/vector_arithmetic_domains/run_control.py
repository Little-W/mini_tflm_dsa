#!/usr/bin/env python3
"""从实际配置检查器和向量状态机证明运算范围与写入互斥关系。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--bus-width", type=int, default=64)
    parser.add_argument("--tile", type=int, default=16)
    parser.add_argument("--pes", type=int, default=8)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / "rtl/npu/conv/vector_engine.sv"
    body = source.read_text().replace("module vector_engine #(", "module vector_domain_control #(", 1)
    position = body.index("endmodule")
    body = body[:position] + """
  logic [3:0] proof_opcode, proof_cfg_opcode;
  logic signed [31:0] proof_min, proof_max, proof_offset;
  assign proof_opcode = c.op;
  assign proof_cfg_opcode = cfg.op;
  assign proof_min = c.activation_min;
  assign proof_max = c.activation_max;
  assign proof_offset = c.output_offset;
  always_comb if (rst_n) begin
    assert(!(state == EXECUTE_COMMIT && softmax_s8));
    assert(!soft_exp_we || state == SOFT_LUT_WAIT);
    if (state == CHECK || state == CHECK_WAIT) assert(!q_active);
    if (result_quant_write) begin
      assert(proof_min[31:8] == {24{proof_min[7]}});
      assert(proof_max[31:8] == {24{proof_max[7]}});
      assert(proof_offset[31:8] == {24{proof_offset[7]}});
      assert(proof_min <= proof_max);
    end
    if (softmax_s8) begin
      case (state)
        IDLE, CHECK, CHECK_WAIT, CONFIGURE, VECTOR_INIT, LOAD_REQ, LOAD_WAIT,
        SOFT_START, SOFT_RUN, SOFT_LUT_REQ, SOFT_LUT_WAIT, WRITE_PREP,
        DRAIN, DONE, FAILED: ;
        default: assert(1'b0);
      endcase
      if (state == LOAD_REQ || state == LOAD_WAIT) assert(load_kind == LD_A);
    end
    if ((depthwise || add_s8) && state != IDLE && state != CHECK &&
        state != CHECK_WAIT && state != FAILED && state != DONE) begin
      assert(proof_min[31:8] == {24{proof_min[7]}});
      assert(proof_max[31:8] == {24{proof_max[7]}});
      assert(proof_offset[31:8] == {24{proof_offset[7]}});
      assert(proof_min <= proof_max);
    end
  end
""" + body[position:]
    proof = out / "control.sv"
    proof.write_text(body)
    folder = ROOT / "rtl/npu/conv"
    files = [folder / "conv_im2col_pkg.sv", folder / "vector_engine_pkg.sv"]
    files += [path for path in sorted(folder.glob("*.sv")) if path not in files and path != source]
    files += [ROOT / "rtl/common" / name for name in ("regfile.v", "pseudo_dual_port_ram.v", "add_equal.sv", "onehot_check.sv")]
    files.append(proof)
    hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in files[:-1] + [source, Path(__file__).resolve(), Path(__file__).with_name("control_worker.py")]}
    script = out / "prepare.ys"
    script.write_text("read_slang -D SYNTHESIS=1 -D ASIC_SYNTHESIS=1 --top vector_domain_control " +
                      f"-GTILE={args.tile} -GPE_COUNT={args.pes} -GBUS_WIDTH={args.bus_width} " +
                      " ".join(shlex.quote(str(path)) for path in files) + f"""
delete -output vector_domain_control/w:*
prep -top vector_domain_control -flatten
async2sync
setattr -unset keep
opt -full
chformal -lower
opt_clean
write_rtlil {out}/control.il
write_json {out}/control.json
""")
    with (out / "prepare.log").open("w") as stream:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                       cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    with (out / "formal.log").open("w") as stream:
        subprocess.run([sys.executable, str(Path(__file__).with_name("control_worker.py")), str(out)],
                       cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    result = json.loads((out / "control_summary.json").read_text())
    if hashes != {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in hashes}:
        raise RuntimeError("验证期间源码发生变化")
    result.update(source_sha256=hashes, tile=args.tile, pes=args.pes, bus_width=args.bus_width)
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
