#!/usr/bin/env python3
"""对缓存地址上下界、自然字起点和填充尾地址执行全部输入比较。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_path = root / 'rtl/npu/dma/cache/conv_windowed_cache.sv'
    if not source_path.is_file():
        source_path = source_path.with_name('conv_read_cache.sv')
    source = source_path.read_text()
    start = source.index('  assign range_i_a =')
    block = source[start:source.index('  localparam int p_cfg_idle_width', start)]
    expressions = '\n'.join(re.search(r'  assign ' + name + r'\s*=.*?;', source, re.S)[0]
                            for name in ('select_line_base', 'select_first', 'fill_candidate_line_base',
                                         'fill_candidate_end_wide', 'fill_candidate_end'))
    proof = out / 'ranges.sv'
    proof.write_text('''module cache_ranges_proof #(
    parameter int LINE_BYTES=128, READ_WIDTH=64
) (
    input logic [31:0] req_addr, pf_addr, demand_addr, prefetch_addr,
    input logic [31:0] reference_addr, select_addr, base_q, end_q,
    input logic bypass_q,
    output logic equivalent
);
    localparam int LB=$clog2(LINE_BYTES), p_read_bytes=READ_WIDTH/8, p_read_shift=$clog2(p_read_bytes);
    logic [31:0] reference_next_address, reference_next;
    logic unused_reference_next_carry;
    logic [11:0][31:0] range_i_a, range_i_b;
    logic [11:0] range_below, unused_range_equal, reference_below;
    logic fill_end_exceeds_tensor, unused_fill_end_equal;
    logic [32:0] fill_candidate_end_wide, reference_end;
    logic [31:0] select_line_base, select_first, fill_candidate_line_base, fill_candidate_end;
    logic [31:0] reference_line_base;
''' + block + expressions + '''
    assign reference_next = reference_addr + 32'(LINE_BYTES);
    assign reference_below = {
        {demand_addr[31:p_read_shift], {p_read_shift{1'b0}}} < base_q,
        select_line_base < base_q,
        reference_next < end_q, reference_next < base_q,
        prefetch_addr < end_q, prefetch_addr < base_q,
        demand_addr < end_q, demand_addr < base_q,
        pf_addr < end_q, pf_addr < base_q,
        req_addr < end_q, req_addr < base_q};
    assign reference_line_base = bypass_q ?
        {demand_addr[31:p_read_shift], {p_read_shift{1'b0}}} : {select_addr[31:LB], {LB{1'b0}}};
    assign reference_end = {1'b0, reference_line_base} + 33'(bypass_q ? p_read_bytes : LINE_BYTES);
    assign equivalent = range_below == reference_below && reference_next_address == reference_next &&
        select_first == (select_line_base < base_q ? base_q : select_line_base) &&
        fill_candidate_end == (reference_end > {1'b0,end_q} ? end_q : reference_end[31:0]);
endmodule
''')
    sources = []
    for name in ('parallel_prefix_add.sv', 'unsigned_compare.sv'):
        target = out / name
        target.write_bytes((root / 'rtl/common' / name).read_bytes())
        sources.append(target)
    summary = {'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
               'input_bits': 257, 'input_constraints': [], 'runs': []}
    for line_bytes, read_width, fpga in ((line, width, mode) for line in (16,128)
                                       for width in (32,64,128) for mode in (0,1)):
        name=f'l{line_bytes}_r{read_width}_f{fpga}'
        script, log = out / (name+'.ys'), out / (name+'.log')
        script.write_text('read_slang --top cache_ranges_proof ' +
                          f'-GLINE_BYTES={line_bytes} -GREAD_WIDTH={read_width} ' +
                          ('-D XILINX_FPGA=1 ' if fpga else '') + shlex.join(map(str,[*sources,proof])) + '\n' +
                          'prep -top cache_ranges_proof -flatten\ncheck -assert\n' +
                          'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                           stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=180)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise RuntimeError('Cache range comparison did not complete')
        summary['runs'].append({'line_bytes':line_bytes,'read_width':read_width,'xilinx_fpga':bool(fpga),
                                'passed':True,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
        print('CACHE_RANGES_PASS',name,flush=True)
    summary['passed']=True
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')


if __name__=='__main__':
    main()
