#!/usr/bin/env python3
"""检查部分和读取使能的完整共享存储行为及所有四态输入组合。"""
from __future__ import annotations

import argparse
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = '584233d8'
HELPER = 'rtl/npu/buffers/ps_channel_read_enable.sv'
spec = spec_from_file_location('shared_read_control', ROOT / 'test/ps_shared_read_control/run_shared.py')
support = module_from_spec(spec)
spec.loader.exec_module(support)
support.HELPERS.append(HELPER)


def helper_checks(out):
    source = out / 'read_enable_comparison.sv'
    source.write_text('''// 对请求、地址、银行和两种访问许可的全部四态组合进行比较。
module tb;
 logic [4:0] terms;
 wire result;
 wire reference = (terms[3] && terms[4]) && ((terms[0] && terms[1]) && terms[2]);
 ps_channel_read_enable u_read_enable (
 .i_read_request(terms[0]),.i_address_valid(terms[1]),.i_bank_match(terms[2]),
 .i_access_enabled(terms[3]),.i_path_enable(terms[4]),.o_enable(result));
 function automatic logic state_value(input integer value);
 case(value)0:state_value=0;1:state_value=1;2:state_value=1'bx;default:state_value=1'bz;endcase
 endfunction
 initial begin
 for(integer sample=0;sample<1024;sample++)begin
  for(integer bit_index=0;bit_index<5;bit_index++)terms[bit_index]=state_value((sample>>(2*bit_index))&3);
  #1;
  if(result!==reference)$fatal(1,"Read enable differs sample=%0d",sample);
 end
 $display("READ_ENABLE_FOUR_STATE_PASS 1024");$finish;
 end
endmodule
''')
    records = []
    for mode in ['generic', 'fpga']:
        flags = [] if mode == 'generic' else ['-DSYNTHESIS=1', '-DXILINX_FPGA=1']
        binary, log = out / (mode + '.vvp'), out / (mode + '.log')
        support.execute(['iverilog', '-g2012', '-s', 'tb', *flags, '-o', binary,
                         source, ROOT / HELPER], out / (mode + '_compile.log'))
        text = support.execute(['vvp', binary], log)
        assert 'READ_ENABLE_FOUR_STATE_PASS 1024' in text
        records.append(dict(mode=mode, passed=True, comparisons=1024,
                            log_sha256=support.digest(log)))
    return dict(passed=True, source_sha256=support.digest(ROOT / HELPER),
                testbench_sha256=support.digest(source), runs=records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default=REFERENCE)
    parser.add_argument('--skip-memory', action='store_true')
    parser.add_argument('--memory-only', action='store_true')
    parser.add_argument('--cycles', type=int, default=8192)
    parser.add_argument('--modes', nargs='+', choices=['generic', 'fpga'], default=['generic', 'fpga'])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = sys.argv
    sys.argv = [str(ROOT / 'test/ps_shared_read_control/run_shared.py'), '--out', str(out / 'channel'),
                '--reference', args.reference, '--cycles', str(args.cycles), '--modes', *args.modes]
    if args.skip_memory:
        sys.argv.append('--skip-memory')
    if args.memory_only:
        sys.argv.append('--memory-only')
    try:
        support.main()
    finally:
        sys.argv = original
    channel = json.loads((out / 'channel/summary.json').read_text())
    helper = out / 'helper'
    helper.mkdir(exist_ok=True)
    report = dict(passed=channel['passed'], reference=args.reference,
                  runner_sha256=support.digest(Path(__file__)), channel=channel,
                  helper_four_state=helper_checks(helper))
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(passed=report['passed'], proofs=len(channel['command_proofs']),
                         memory_modes=len(channel['memory_tests']), four_state_comparisons=2048)), flush=True)


if __name__ == '__main__':
    main()
