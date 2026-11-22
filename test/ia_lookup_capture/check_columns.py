#!/usr/bin/env python3
"""验证实际列掩码及窄位宽参数分支的状态和全部 DMA 写入输出。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/loaders/ia_loader.sv')
PROFILES = ((2, 1, 16), (3, 2, 8), (4, 32, 4), (8, 16, 8),
            (16, 32, 4), (16, 32, 8), (16, 32, 16), (16, 4, 8),
            (16, 4, 1), (32, 32, 8), (64, 32, 16))


def extract(text: str, name: str) -> str:
    header = re.search(r'// DMA 接入[^\n]*\n\s*// =+\n', text)
    if not header:
        raise RuntimeError('找不到 DMA 写入状态区域')
    stop = text.index('    // Every read, including im2col', header.end())
    state = text[header.end():stop]
    first = text.index('    generate\n        for (genvar dma_i', stop)
    last = text.index('    endgenerate\n', first) + len('    endgenerate\n')
    writes = text[first:last]
    return f'''module {name} #(
  parameter int SIZE=16,REG_WIDTH=32,DMA_LANES=8,DATA_WIDTH=16,
  localparam int LOG2_SIZE=$clog2(SIZE)
)(input logic clk,rst_n,ext_dma_start,
  input logic [REG_WIDTH-1:0] descriptor_cols,
  input logic [LOG2_SIZE-1:0] ext_dma_wr_col_base,
  input logic signed [DATA_WIDTH-1:0] ext_dma_wr_data [DMA_LANES],
  input logic ext_dma_wr_valid [DMA_LANES],
  output logic [DMA_LANES*(DATA_WIDTH+1)-1:0] observed);
  typedef struct packed {{logic [REG_WIDTH-1:0] cols;}} descriptor_t;
  descriptor_t dma_descriptor;
  logic signed [DATA_WIDTH-1:0] tl_wr_data [DMA_LANES];
  logic tl_wr_valid [DMA_LANES];
  assign dma_descriptor.cols=descriptor_cols;
{state}
{writes}
  for(genvar lane=0;lane<DMA_LANES;lane++) begin:g_output
    assign observed[lane*(DATA_WIDTH+1)+:(DATA_WIDTH+1)]={{tl_wr_valid[lane],tl_wr_data[lane]}};
  end
endmodule
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    roots = {'reference': args.reference_root.resolve(), 'current': args.source_root.resolve()}
    model = out / 'columns.sv'
    model.write_text(''.join(extract((root / SOURCE).read_text(), name) for name, root in roots.items()) + '''
module comparison #(
  parameter int SIZE=16,REG_WIDTH=32,DMA_LANES=8,DATA_WIDTH=16,
  localparam int LOG2_SIZE=$clog2(SIZE)
)(input logic clk,rst_n,ext_dma_start,
  input logic [REG_WIDTH-1:0] descriptor_cols,
  input logic [LOG2_SIZE-1:0] ext_dma_wr_col_base,
  input logic signed [DATA_WIDTH-1:0] ext_dma_wr_data [DMA_LANES],
  input logic ext_dma_wr_valid [DMA_LANES],
  output logic equivalent);
  logic [DMA_LANES*(DATA_WIDTH+1)-1:0] old_value,new_value;
  reference #(.SIZE(SIZE),.REG_WIDTH(REG_WIDTH),.DMA_LANES(DMA_LANES),.DATA_WIDTH(DATA_WIDTH))
    u_reference(.*,.observed(old_value));
  current #(.SIZE(SIZE),.REG_WIDTH(REG_WIDTH),.DMA_LANES(DMA_LANES),.DATA_WIDTH(DATA_WIDTH))
    u_current(.*,.observed(new_value));
  assign equivalent=old_value==new_value;
endmodule
''')
    reports = []
    for size, width, lanes in PROFILES:
        name = f's{size}_w{width}_l{lanes}'
        script, log = out / (name + '.ys'), out / (name + '.log')
        script.write_text('read_slang --top comparison ' +
                          f'-GSIZE={size} -GREG_WIDTH={width} -GDMA_LANES={lanes} ' +
                          shlex.quote(str(model)) + '\nprep -top comparison -flatten\n'
                          'async2sync\nopt_clean\n'
                          'sat -verify -seq 2 -tempinduct -set-at 1 rst_n 0 -prove equivalent 1 -maxsteps 8\n')
        with log.open('w') as stream:
            completed = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                        '--worker', str(script)], cwd=ROOT, stdout=stream,
                                       stderr=subprocess.STDOUT, timeout=60)
        passed = completed.returncode == 0 and 'Induction step proven: SUCCESS!' in log.read_text()
        reports.append({'size': size, 'register_width': width, 'lanes': lanes, 'passed': passed,
                        'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
        if not passed:
            raise RuntimeError('列状态证明未完成: ' + str(log))
    result = {'passed': True, 'external_inputs_constrained': False,
              'source_sha256': {name: hashlib.sha256((root / SOURCE).read_bytes()).hexdigest()
                                for name, root in roots.items()}, 'profiles': reports}
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
