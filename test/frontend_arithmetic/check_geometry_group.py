#!/usr/bin/env python3
"""验证几何模块的通道组范围判断及完整模块的输出、寄存状态。"""
from __future__ import annotations

from formal_compilation import slang_command

from concurrent.futures import ThreadPoolExecutor
import argparse
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

from check_word_match import ROOT, bench, digest, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source', type=Path,
                        default=ROOT/'rtl/npu/conv/conv_im2col_geometry.sv')
    parser.add_argument('--helper', type=Path,
                        default=ROOT/'rtl/common/unsigned_sum_le.sv')
    parser.add_argument('--reference', default='9bd6488c')
    parser.add_argument('--compilation', choices=('generic', 'synthesis', 'both'), default='both')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source, helper = args.source.resolve(), args.helper.resolve()
    dependencies = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    reference_text = subprocess.check_output(
        ['git', 'show', args.reference+':rtl/npu/conv/conv_im2col_geometry.sv'],
        cwd=ROOT, text=True)
    reference = out/'reference_geometry.sv'
    reference.write_text(reference_text)
    sources = {
        'reference': dependencies([reference], ROOT),
        'candidate': dependencies([source, helper], ROOT),
    }
    hashes = {str(path): digest(path) for items in sources.values() for path in items}
    cases = []
    for lanes in (2, 8):
        for registered in (0, 1):
            for synthesis in ((0, 1) if args.compilation == 'both' else
                              (int(args.compilation == 'synthesis'),)):
                name = f'lanes{lanes}_registered{registered}_synthesis{synthesis}'
                options = ['-I'+str(ROOT/'include'), '-Gp_lanes='+str(lanes),
                           '-Gp_line_bytes=128', '-Gp_register_descriptor='+str(registered)]
                if synthesis:
                    options += ['-DSYNTHESIS=1', '-DXILINX_FPGA=1']
                commands = []
                for label, paths in sources.items():
                    commands += [
                        slang_command(options)+'--top conv_im2col_geometry '+shlex.join([*options, *map(str, paths)]),
                        'setattr -mod -unset keep_hierarchy', 'setattr -unset keep_hierarchy',
                        'prep -top conv_im2col_geometry -flatten', 'memory_map',
                        'async2sync', 'opt -full', 'opt_clean -purge',
                        'rename -top '+label, 'design -stash '+label,
                    ]
                commands += [
                    'design -copy-from reference -as reference reference',
                    'design -copy-from candidate -as candidate candidate',
                    'equiv_make reference candidate proof', 'hierarchy -top proof',
                    'equiv_simple -seq 2', 'opt_clean', 'equiv_induct -seq 3',
                    'equiv_status -assert',
                ]
                script = out/(name+'.ys')
                script.write_text('\n'.join(commands)+'\n')
                cases.append((name, script))

    def execute(item):
        name, script = item
        log = out/(name+'.log')
        run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
        if 'Equivalence successfully proven!' not in log.read_text():
            raise ValueError('完整几何模块证明未完成：'+name)
        counts = re.findall(r'Found (\d+) \$equiv cells', log.read_text())
        print(name+' PASS', flush=True)
        return dict(name=name, passed=True, equivalence_cells=int(counts[-1]),
                    log_sha256=digest(log))

    with ThreadPoolExecutor(max_workers=2) as pool:
        formal = list(pool.map(execute, cases))

    actual = re.search(r'  unsigned_sum_le #\(\.p_width\(16\)\) u_cfg_group_within_input \(.*?\n  \);',
                       source.read_text(), re.S)
    expected = re.search(r'  assign cfg_group_within_input =\s*.*?;', reference_text, re.S)
    if actual is None or expected is None:
        raise ValueError('通道组范围的生产计算语句未找到')
    actual_text = actual.group(0)
    expected_text = expected.group(0).replace('cfg_group_within_input', 'reference_within')
    for field, signal in [('group_offset', 'offset'), ('group_c', 'channels'), ('input_c', 'limit')]:
        actual_text = actual_text.replace('i_cfg.'+field, signal)
        expected_text = expected_text.replace('i_cfg.'+field, signal)
    model = out/'group_comparison.sv'
    model.write_text('''module match_proof(input logic [23:0] i_a,i_b,output logic equivalent);
logic [15:0] offset,channels,limit;
logic cfg_group_within_input,reference_within;
assign {offset,channels,limit}={i_a,i_b};
'''+actual_text+'\n'+expected_text+'''
assign equivalent=cfg_group_within_input===reference_within;
endmodule
''')
    tb = out/'tb.sv'
    tb.write_text(bench(24))
    hashes[str(model)] = digest(model)
    hashes[str(tb)] = digest(tb)
    simulation = []
    for synthesis in (0, 1):
        options = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] if synthesis else []
        binary = out/f'synthesis{synthesis}.vvp'
        run(['iverilog', '-g2012', *options, '-s', 'tb', '-o', binary, helper, model, tb],
            out/f'compile{synthesis}.log')
        log = out/f'simulation{synthesis}.log'
        run(['vvp', binary], log)
        if 'WORD_MATCH_PASS width=24 checks=3170' not in log.read_text():
            raise ValueError('通道组范围四态检查未完成')
        simulation.append(dict(synthesis=synthesis, passed=True, checks=3170,
                               log_sha256=digest(log)))
    if any(digest(path) != value for path, value in hashes.items()):
        raise ValueError('验证期间源码内容发生变化')
    report = dict(passed=True, reference=args.reference, compilation=args.compilation, input_assumptions=[],
                  source_sha256=hashes, formal=formal, four_state=simulation)
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(f'GEOMETRY_GROUP_PASS formal={len(formal)} four_state=6340')


if __name__ == '__main__':
    main()
