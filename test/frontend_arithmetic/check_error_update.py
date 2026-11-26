#!/usr/bin/env python3
"""验证错误状态最终选择的完整组合逻辑与四态传播。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import runpy
import shlex
import subprocess
import sys

from check_word_match import ROOT, digest, run
from formal_compilation import slang_command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--helper', type=Path, required=True)
    parser.add_argument('--reference', default='9c3f2718')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    api = runpy.run_path(str(ROOT/'test/conv_frontend/tools/check_error_selection.py'))
    flags = api['FLAGS']
    actual, helper = args.source.resolve(), args.helper.resolve()
    reference = out/'reference.sv'
    original = subprocess.check_output(
        ['git', 'show', args.reference+':rtl/npu/conv/conv_im2col_error_update.sv'],
        cwd=ROOT, text=True)
    reference.write_text(original.replace('module conv_im2col_error_update', 'module reference'))
    declarations = ',\n'.join('input logic '+name for name in flags)
    connections = ', '.join('.'+name+'('+name+')' for name in ['i_state', *flags])
    model = out/'model.sv'
    model.write_text('module proof(input logic [26:0] i_state,\n'+declarations+''',
      output logic o_error,o_tile_error,expected_error,expected_tile_error,
      output logic error_equal,tile_error_equal);
    conv_im2col_error_update u_actual('''+connections+''',.o_error,.o_tile_error);
    reference u_reference('''+connections+''',.o_error(expected_error),.o_tile_error(expected_tile_error));
    assign error_equal=o_error===expected_error;
    assign tile_error_equal=o_tile_error===expected_tile_error;
    endmodule
    ''')
    resolver = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources = resolver([actual, helper, reference, model], ROOT)
    hashes = {str(path): digest(path) for path in sources}
    formal = []
    for synthesis in (False, True):
        options = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] if synthesis else []
        name = 'synthesis' if synthesis else 'generic'
        script, log = out/(name+'.ys'), out/(name+'.log')
        script.write_text(
            slang_command(options)+'--top proof '+shlex.join([*options, *map(str, sources)])+
            '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
            'prep -top proof -flatten\ncheck -assert\n'+
            ''.join('sat -verify -prove '+signal+' 1 -show-inputs -show-outputs\n'
                    for signal in ['error_equal', 'tile_error_equal']))
        run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
        if log.read_text().count('SAT proof finished - no model found: SUCCESS!') != 2:
            raise ValueError('完整错误标志证明未完成')
        formal.append(dict(synthesis=synthesis, passed=True, outputs=2, log_sha256=digest(log)))
    text, checks = api['bench']()
    tb, binary = out/'tb.sv', out/'simulation.vvp'
    tb.write_text(text)
    run(['iverilog', '-g2012', '-s', 'tb', '-o', binary, *sources, tb], out/'compile.log')
    log = out/'simulation.log'
    run(['vvp', binary], log)
    if 'ERROR_SELECTION_PASS checks='+str(checks) not in log.read_text():
        raise ValueError('错误标志四态检查未完成')
    if any(digest(path) != value for path, value in hashes.items()):
        raise ValueError('验证期间源文件发生变化')
    report = dict(passed=True, input_assumptions=[], reference=args.reference,
                  source_sha256=hashes, formal=formal,
                  four_state=dict(passed=True, checks=checks, log_sha256=digest(log)))
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print('ERROR_UPDATE_PASS formal=2 four_state='+str(checks))


if __name__ == '__main__':
    main()
