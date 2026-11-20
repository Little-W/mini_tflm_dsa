#!/usr/bin/env python3
"""用实际向量状态转移和窗口队列证明输入存储写入来源的归属。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--bus-width', type=int, default=64)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = (ROOT / 'rtl/npu/conv/vector_engine.sv').read_text()
    body = source.replace('module vector_engine #(', 'module input_write_control #(', 1)
    declarations = '''
  logic win_req_ready, win_rsp_valid;
  logic [1:0] win_rsp_tag;
  logic [31:0] win_rsp_col;
  logic signed [15:0] win_rsp_data[4];
  logic [3:0] win_rsp_mask;
  logic win_rsp_last,win_rsp_error,win_busy;
'''
    remove = ['  input logic win_req_ready,\n', '  input logic win_rsp_valid,\n',
              '  input logic [1:0] win_rsp_tag,\n', '  input logic [31:0] win_rsp_col,\n',
              '  input logic signed [15:0] win_rsp_data[4],\n',
              '  input logic [3:0] win_rsp_mask,\n',
              '  input logic win_rsp_last,win_rsp_error,win_busy,\n']
    for item in remove:
        assert body.count(item) == 1, item
        body = body.replace(item, '', 1)
    port_end = body.index('\n);')
    body = body[:port_end] + ''',
  input logic proof_enable, proof_frontend_ready, proof_frontend_valid,
  input logic [31:0] proof_frontend_col,
  input logic signed [15:0] proof_frontend_data[4],
  input logic [3:0] proof_frontend_mask,
  input logic proof_frontend_last, proof_frontend_error
''' + body[port_end:]
    declaration_pos = body.index('  import vector_engine_pkg::*;')
    body = body[:declaration_pos] + declarations + body[declaration_pos:]
    position = body.index('endmodule')
    body = body[:position] + (HERE / 'control_template.sv.inc').read_text() + body[position:]
    design = out / 'control.sv'
    design.write_text(body)
    files = [ROOT / 'rtl/npu/conv' / name for name in ('conv_im2col_pkg.sv', 'vector_engine_pkg.sv')]
    files += [p for p in sorted((ROOT / 'rtl/npu/conv').glob('*.sv'))
              if p not in files and p.name != 'vector_engine.sv']
    files += [ROOT / 'rtl/common' / name for name in ('pseudo_dual_port_ram.v', 'regfile.v', 'add_equal.sv')]
    files += [ROOT / 'rtl/npu/dma/conv_window_queue.sv', design]
    checked_files = files[:-1] + [ROOT / 'rtl/npu/conv/vector_engine.sv',
                                  Path(__file__).resolve(), HERE / 'control_worker.py',
                                  HERE / 'control_template.sv.inc']
    source_hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in checked_files}
    script = out / 'prepare.ys'
    script.write_text('read_slang -D SYNTHESIS=1 -D ASIC_SYNTHESIS=1 --top input_write_control '
                      f'-GTILE=16 -GPE_COUNT=8 -GBUS_WIDTH={args.bus_width} ' +
                      ' '.join(shlex.quote(str(p)) for p in files) + '\n' + f'''
delete -output input_write_control/w:*
prep -top input_write_control -flatten
async2sync
setattr -unset keep
opt -full
chformal -lower
opt_clean
write_rtlil {out}/control.il
write_json {out}/control.json
''')
    log = out / 'prepare.log'
    with log.open('w') as stream:
        result = subprocess.run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py',
                                 '--worker', script], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(log.read_text()[-8000:])
    with (out / 'formal.log').open('w') as stream:
        result = subprocess.run([sys.executable, HERE / 'control_worker.py', out], cwd=ROOT,
                                stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError((out / 'formal.log').read_text()[-8000:])
    summary = json.loads((out / 'control_summary.json').read_text())
    assert source == (ROOT / 'rtl/npu/conv/vector_engine.sv').read_text()
    assert source_hashes == {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in checked_files}
    summary['source_sha256'] = source_hashes
    summary['bus_width'] = args.bus_width
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
