#!/usr/bin/env python3
"""保留实际状态机和分母寄存器，证明每个 AVG_START 使用前一拍的分母。"""
from __future__ import annotations

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
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--bus-width', type=int, default=64)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT/'rtl/npu/conv/vector_engine.sv'
    body = source.read_text().replace('module vector_engine #(', 'module reciprocal_control #(', 1)
    end = body.index('endmodule')
    body = body[:end]+'''
  logic [TAP_COUNT_W-1:0] proof_sampled_taps;
  always_ff @(posedge clk) proof_sampled_taps <= valid_taps;
  always_comb begin
    if (rst_n && state==AVG_START) begin
      assert(valid_taps==proof_sampled_taps);
    end
  end
'''+body[end:]
    proof = out/'control.sv'
    proof.write_text(body)
    conv = ROOT/'rtl/npu/conv'
    sources = [conv/'conv_im2col_pkg.sv', conv/'vector_engine_pkg.sv']
    sources += [path for path in sorted(conv.glob('*.sv')) if path not in sources and path != source]
    sources += list(sorted((ROOT/'rtl/common').glob('*.v')))+list(sorted((ROOT/'rtl/common').glob('*.sv')))
    script = out/'prepare.ys'
    script.write_text('read_slang -D SYNTHESIS=1 -D ASIC_SYNTHESIS=1 --top reciprocal_control '+
                      f'-GTILE=16 -GPE_COUNT=8 -GBUS_WIDTH={args.bus_width} '+
                      ' '.join(shlex.quote(str(path)) for path in sources+[proof])+f'''
delete -output reciprocal_control/w:*
prep -top reciprocal_control -flatten
async2sync
setattr -unset keep
opt -full
chformal -lower
opt_clean
write_json {out}/control.json
''')
    with (out/'prepare.log').open('w') as stream:
        subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)],
                       cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    with (out/'formal.log').open('w') as stream:
        subprocess.run([sys.executable, str(Path(__file__).with_name('control_worker.py')), str(out)],
                       cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    summary = json.loads((out/'summary.json').read_text())
    summary.update(bus_width=args.bus_width,
                   source_sha256={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                  for path in sources+[source, Path(__file__).resolve(), Path(__file__).with_name('control_worker.py')]})
    (out/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
