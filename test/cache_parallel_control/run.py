#!/usr/bin/env python3
"""验证缓存状态归并和地址比较的完整状态等价及四态组合行为。"""
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
CACHE = Path('rtl/npu/dma/cache/conv_windowed_cache.sv')
REQUEST = Path('rtl/npu/dma/cache/conv_cache_request_path.sv')
PROFILES = [dict(SETS=4, WAYS=1, LINE_BYTES=16, BUS_WIDTH=32, READ_WIDTH=32, DEMAND_DEPTH=1),
            dict(SETS=4, WAYS=2, LINE_BYTES=16, BUS_WIDTH=64, READ_WIDTH=64, DEMAND_DEPTH=2),
            dict(SETS=16, WAYS=2, LINE_BYTES=128, BUS_WIDTH=64, READ_WIDTH=64, DEMAND_DEPTH=2)]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def four_state_model(label, cache, request):
    cfg = cache[cache.index('  localparam int p_cfg_idle_width ='):
                cache.index('  localparam int WAY_DEPTH =')]
    begin = ('  localparam int p_address_compare_groups =' if label == 'reference' else
             '  logic select_demand_address_matches,')
    addresses = cache[cache.index(begin):cache.index('  logic select_fill_capacity_ready,')]
    tags = request[request.index('  if (DEMAND_DEPTH > 1) begin : g_registered_tag_compare'):
                   request.index('  end else begin', request.index('  if (DEMAND_DEPTH > 1) begin : g_registered_tag_compare'))]
    tags += '  end\n'
    result = ('{(&select_demand_address_match), (&select_prefetch_address_match)}' if label == 'reference'
              else '{select_demand_address_matches, select_prefetch_address_matches}')
    return f'''module {label} #(parameter integer DQ_CW=2, LB=7, WAYS=2)(
  input wire [1:0] fill_state, fg_state,
  input wire clearing, pf_active_valid, offer_valid, select_stage_valid,
  input wire [3:0] pf_count,
  input wire [DQ_CW-1:0] outstanding_count, request_count, response_count,
  input wire [31:0] demand_addr, pf_addr, select_addr, work_addr,
  input wire [WAYS-1:0][31:LB] lookup_tag,
  input wire [WAYS-1:0] valid_lookup,
  output wire [2+2*WAYS:0] result
);
  localparam integer PF_CW=4, DEMAND_DEPTH=2;
  localparam [1:0] F_IDLE=0;
  wire cfg_ready;
  wire [WAYS-1:0] work_tag_hits, demand_tag_hits;
  typedef struct packed {{logic [31:0] address;}} request_t;
  request_t work_request;
  assign work_request.address = work_addr;
{cfg}
{addresses}
{tags}
  assign result = {{cfg_ready, {result}, work_tag_hits, demand_tag_hits}};
endmodule
'''


def four_state_bench(dq_width, lb, ways):
    width = 8 + 4 + 3*dq_width + 128 + ways*(32-lb) + ways
    return f'''module tb;
  localparam integer DQ_CW={dq_width}, LB={lb}, WAYS={ways}, WIDTH={width};
  reg [WIDTH-1:0] stimulus, saved;
  wire [1:0] fill_state, fg_state;
  wire clearing, pf_active_valid, offer_valid, select_stage_valid;
  wire [3:0] pf_count;
  wire [DQ_CW-1:0] outstanding_count, request_count, response_count;
  wire [31:0] demand_addr, pf_addr, select_addr, work_addr;
  wire [WAYS-1:0][31:LB] lookup_tag;
  wire [WAYS-1:0] valid_lookup;
  wire [2+2*WAYS:0] a, b;
  assign {{fill_state,fg_state,clearing,pf_active_valid,offer_valid,select_stage_valid,
    pf_count,outstanding_count,request_count,response_count,demand_addr,pf_addr,
    select_addr,work_addr,lookup_tag,valid_lookup}} = stimulus;
  reference #(.DQ_CW(DQ_CW),.LB(LB),.WAYS(WAYS)) u_reference (.*,.result(a));
  current #(.DQ_CW(DQ_CW),.LB(LB),.WAYS(WAYS)) u_current (.*,.result(b));
  reg [31:0] rng=32'h981dab43;
  integer checks=0;
  task check;
    #1; if(a!==b) $fatal(1,"缓存组合结果不同 stimulus=%b reference=%b current=%b",stimulus,a,b);
    checks=checks+1;
  endtask
  task randomize;
    for(integer bit_index=0;bit_index<WIDTH;bit_index=bit_index+1) begin
      rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);stimulus[bit_index]=rng[0];
    end
  endtask
  initial begin
    stimulus='0;check();stimulus='1;check();stimulus='x;check();stimulus='z;check();
    for(integer trial=0;trial<512;trial=trial+1) begin
      randomize();check();saved=stimulus;
      for(integer bit_index=0;bit_index<WIDTH;bit_index=bit_index+1) begin
        stimulus=saved;stimulus[bit_index]=1'bx;check();
        stimulus=saved;stimulus[bit_index]=1'bz;check();
      end
    end
    // 相等地址和空闲状态分别覆盖比较归并的所有有效结果。
    for(integer bit_index=0;bit_index<WIDTH;bit_index=bit_index+1) begin
      stimulus='0;stimulus[bit_index]=1'b1;check();
      stimulus='0;stimulus[bit_index]=1'bx;check();
      stimulus='0;stimulus[bit_index]=1'bz;check();
    end
    $display("CACHE_CONTROL_FOUR_STATE_PASS checks=%0d",checks);$finish;
  end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='54a96b45')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--four-state-only', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    resolver = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    originals = {}
    references = []
    for path in (CACHE, REQUEST):
        text = subprocess.check_output(['git', 'show', args.reference+':'+str(path)], cwd=ROOT, text=True)
        originals[path] = text
        copy = out/('reference_'+path.name)
        copy.write_text(text)
        references.append(copy)
    current_files = resolver([ROOT/CACHE, ROOT/REQUEST], ROOT)
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in current_files}
    report = dict(reference=args.reference, source_sha256=hashes, formal=[], four_state=[])
    if not args.four_state_only:
        for mode, flags in [('generic', ''), ('fpga', '-DSYNTHESIS=1 -DXILINX_FPGA=1')]:
            for index, parameters in enumerate(PROFILES):
                options = ' '.join(f'-G{key}={value}' for key, value in parameters.items())
                commands = []
                for label, inputs in [('reference', references), ('current', [ROOT/CACHE, ROOT/REQUEST])]:
                    sources = resolver(inputs, ROOT)
                    commands += [f'read_slang {flags} --top conv_windowed_cache {options} '+shlex.join(map(str,sources)),
                                 'prep -top conv_windowed_cache -flatten', 'memory_map', 'async2sync', 'opt_clean',
                                 f'rename conv_windowed_cache {label}', f'design -stash {label}']
                commands += ['design -copy-from reference -as reference reference',
                             'design -copy-from current -as current current', 'equiv_make reference current comparison',
                             'hierarchy -top comparison', 'equiv_simple -short -seq 1', 'opt_clean',
                             'equiv_induct -seq 3', 'equiv_status -assert']
                script, log = out/f'{mode}_{index}.ys', out/f'{mode}_{index}.log'
                script.write_text('\n'.join(commands)+'\n')
                with log.open('w') as stream:
                    subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)],
                                   cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=600)
                counts = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', log.read_text())
                assert counts and int(counts[2]) == 0
                report['formal'].append(dict(mode=mode, parameters=parameters, bits=int(counts[1]), passed=True,
                                             script_sha256=digest(script), log_sha256=digest(log)))
                print(mode, index, counts[1], 'PASS', flush=True)
    models = '\n'.join(four_state_model(label, cache, request) for label, cache, request in (
        ('reference', originals[CACHE], originals[REQUEST]),
        ('current', (ROOT/CACHE).read_text(), (ROOT/REQUEST).read_text())))
    helpers = resolver([ROOT/'rtl/common/zero_reduce.sv', ROOT/'rtl/npu/dma/cache/conv_cache_snapshot_equal.sv'], ROOT)
    for index, (dq_width, lb, ways) in enumerate(((1,4,1), (2,7,2), (3,5,4))):
        source, binary, log = out/f'four_state_{index}.sv', out/f'four_state_{index}.vvp', out/f'four_state_{index}.log'
        source.write_text(models+four_state_bench(dq_width,lb,ways))
        with (out/f'four_state_{index}.compile.log').open('w') as stream:
            subprocess.run(['iverilog','-g2012','-s','tb','-o',str(binary),str(source),*map(str,helpers)],
                           stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=120)
        result = subprocess.run(['vvp',str(binary)],capture_output=True,text=True,timeout=120)
        log.write_text(result.stdout+result.stderr)
        match = re.search(r'CACHE_CONTROL_FOUR_STATE_PASS checks=(\d+)', result.stdout)
        assert result.returncode == 0 and match, str(log)
        report['four_state'].append(dict(demand_count_width=dq_width,line_offset_width=lb,ways=ways,
                                         checks=int(match[1]),passed=True,source_sha256=digest(source),log_sha256=digest(log)))
        print('four_state',index,match[1],'PASS',flush=True)
    assert all(digest(ROOT/path)==value for path,value in hashes.items()), '验证期间源文件发生变化'
    report['passed'] = True
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__ == '__main__':
    main()
