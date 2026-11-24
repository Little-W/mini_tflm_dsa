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
    first = source.index('  assign select_line_base')
    expressions = source[first:source.index('  assign ram_wen', first)]
    helpers = []
    for name in ('conv_cache_next_line', 'conv_cache_increment_bit'):
        declaration = 'module ' + name
        if declaration in source:
            start = source.index(declaration)
            helpers.append(source[start:source.index('endmodule', start)+len('endmodule')])
    proof = out / 'ranges.sv'
    proof.write_text('''module cache_ranges_proof #(
    parameter int LINE_BYTES=128, READ_WIDTH=64
) (
    input logic [31:0] req_addr, pf_addr, demand_addr, prefetch_addr,
    input logic [31:0] reference_addr, select_addr, base_q, end_q,
    input logic bypass_q,
    output logic equivalent, next_line_equivalent
);
    localparam int LB=$clog2(LINE_BYTES), p_read_bytes=READ_WIDTH/8, p_read_shift=$clog2(p_read_bytes);
    logic [31:0] reference_next_address, reference_next;
    logic unused_reference_next_carry;
    logic [11:0][31:0] range_i_a, range_i_b;
    logic [11:0] range_below, unused_range_equal, reference_below;
    logic [32:0] reference_end;
    logic [31:0] select_line_base, select_first, fill_candidate_end;
    logic [1:0][31:0] fill_end_candidates;
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
    assign next_line_equivalent = reference_next_address == reference_next;
    assign equivalent = range_below == reference_below && reference_next_address == reference_next &&
        select_first == (select_line_base < base_q ? base_q : select_line_base) &&
        fill_candidate_end == (reference_end > {1'b0,end_q} ? end_q : reference_end[31:0]);
endmodule
''' + '\n'.join(helpers) + '\n')
    sources = []
    for name in ('parallel_prefix_add.sv', 'unsigned_compare.sv'):
        target = out / name
        target.write_bytes((root / 'rtl/common' / name).read_bytes())
        sources.append(target)
    summary = {'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
               'input_bits': 257, 'input_constraints': [], 'runs': []}
    summary['next_line_profiles'] = []
    for line_bytes in (8,16,32,64,128,256):
        name = f'next_line{line_bytes}'
        script, log = out / (name+'.ys'), out / (name+'.log')
        script.write_text('read_slang --top cache_ranges_proof -DSYNTHESIS=1 ' +
                          f'-GLINE_BYTES={line_bytes} ' + shlex.join(map(str,[*sources,proof])) + '\n' +
                          'prep -top cache_ranges_proof -flatten\ncheck -assert\n' +
                          'sat -verify -prove next_line_equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                           stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=180)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise RuntimeError('下一缓存行地址的比较未完成')
        summary['next_line_profiles'].append({'line_bytes':line_bytes,'passed':True,
                                             'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
        print('CACHE_NEXT_LINE_PASS',line_bytes,flush=True)
    for line_bytes, read_width, fpga in ((line, width, mode) for line in (16,128)
                                       for width in (32,64,128) for mode in (0,1)):
        name=f'l{line_bytes}_r{read_width}_f{fpga}'
        script, log = out / (name+'.ys'), out / (name+'.log')
        script.write_text('read_slang --top cache_ranges_proof -DSYNTHESIS=1 ' +
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
    bench = out / 'four_state.sv'
    bench.write_text('''module tb;
    logic [31:0] req_addr=0,pf_addr=0,demand_addr=0,prefetch_addr=0;
    logic [31:0] reference_addr=0,select_addr=0,base_q=0,end_q=0;
    logic bypass_q=0;
    wire equivalent,next_line_equivalent;
    wire [31:0] expected_next_address;
    wire unused_next_carry;
    integer checks=0,unknowns=0;
    cache_ranges_proof #(.LINE_BYTES(128),.READ_WIDTH(128)) dut(.*);
    parallel_prefix_add #(.p_width(32),.p_group_width(4),.p_preserve_groups(1'b1)) u_next_reference (
      .i_a(reference_addr),.i_b(32'd128),.i_carry(1'b0),
      .o_sum(expected_next_address),.o_carry(unused_next_carry));
    initial begin
      for(integer sample=0;sample<20000;sample++)begin
        req_addr=$urandom;pf_addr=$urandom;demand_addr=$urandom;prefetch_addr=$urandom;
        reference_addr=$urandom;select_addr=$urandom;base_q=$urandom;end_q=$urandom;
        bypass_q=1'($urandom);
        if(sample%5==0)bypass_q=1'bx;
        if(sample%7==0)select_addr[sample%32]=1'bz;
        if(sample%11==0)demand_addr[sample%32]=1'bx;
        if(sample%13==0)end_q[sample%32]=1'bz;
        if(sample%3==0)reference_addr[sample%32]=1'bx;
        if(sample%19==0)reference_addr[(sample+1)%32]=1'bz;
        if(sample%17==0)begin select_addr=32'hffffff80;demand_addr=32'hfffffff0;end_q='1;end
        #1;
        if(dut.reference_next_address !== expected_next_address)
          $fatal(1,"Next line address differs at sample %0d",sample);
        if(dut.fill_candidate_end !==
           (dut.reference_end>{1'b0,end_q}?end_q:dut.reference_end[31:0]))
          $fatal(1,"Fill end differs at sample %0d",sample);
        if((^dut.fill_candidate_end)===1'bx)unknowns++;
        checks++;
      end
      if(unknowns==0)$fatal(1,"No unknown fill addresses checked");
      $display("CACHE_FILL_END_FOUR_STATE_PASS checks=%0d unknowns=%0d",checks,unknowns);
      $finish;
    end
endmodule
''')
    binary = out / 'four_state.vvp'
    with (out / 'compile.log').open('w') as stream:
        subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', str(binary),
                        *map(str, sources), str(proof), str(bench)],
                       stdout=stream, stderr=subprocess.STDOUT, check=True)
    with (out / 'four_state.log').open('w') as stream:
        subprocess.run(['vvp', str(binary)], stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=60)
    match = re.search(r'CACHE_FILL_END_FOUR_STATE_PASS checks=(\d+) unknowns=(\d+)',
                      (out / 'four_state.log').read_text())
    if match is None:
        raise RuntimeError('填充尾地址四态比较结果缺失')
    summary['four_state'] = dict(checks=int(match[1]), unknown_results=int(match[2]))
    summary['passed']=True
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')


if __name__=='__main__':
    main()
