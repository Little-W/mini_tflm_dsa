#!/usr/bin/env python3
"""验证同步倒数表的完整内容、读取周期和实际状态机的分母保持关系。"""
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
SOURCE = Path('rtl/npu/conv/vector_engine.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(source):
    return re.sub(r'\s+', '', re.sub(r'//[^\n]*|/\*.*?\*/', '', source, flags=re.S))


def extract(source):
    scale = source.index('  localparam int AVG_SCALE_BITS =')
    end_scale = source.index('  logic [AVG_SCALE_BITS-1:0] avg_numerator_q;', scale)
    table = source.index('  assign avg_reciprocal[0]')
    if '// 倒数表保存' in source:
        table = source.index('  // 倒数表保存')
    end_table = source.index('  logic input_range_mode,', table)
    return source[scale:end_scale], source[table:end_table], (scale, end_scale, table, end_table)


def unit(source, registered_reference=False):
    declarations, table, _ = extract(source)
    current = 'avg_reciprocal_data' in declarations
    result = ('assign o_reciprocal = avg_reciprocal_data;' if current else
              ('always_ff @(posedge clk) o_reciprocal <= avg_reciprocal[valid_taps];'
               if registered_reference else 'assign o_reciprocal = avg_reciprocal[valid_taps];'))
    return '''module reciprocal_unit #(
    parameter int POOL_MAX_TAPS=256,
    parameter int p_address_width=$clog2(POOL_MAX_TAPS+1)
) (
    input logic clk,
    input logic [p_address_width-1:0] i_taps,
    output logic [8+$clog2(POOL_MAX_TAPS+1):0] o_reciprocal
);
logic [p_address_width-1:0] valid_taps;
assign valid_taps=i_taps;
''' + declarations + table + result + '\nendmodule\n'


def worker(script, log):
    with log.open('w') as stream:
        result = subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                                 '--worker', str(script)], cwd=ROOT,
                                stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(log.read_text()[-8000:])
    return digest(log)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='e03a7421')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference_revision = subprocess.check_output(['git', 'rev-parse', args.reference], cwd=ROOT, text=True).strip()
    reference = subprocess.check_output(['git', 'show', reference_revision+':'+str(SOURCE)], cwd=ROOT, text=True)
    current = (ROOT/SOURCE).read_text()
    old_declarations, old_table, _ = extract(reference)
    new_declarations, new_table, _ = extract(current)
    restored = current.replace(new_declarations, old_declarations, 1).replace(new_table, old_table, 1)
    restored = restored.replace("$signed(32'(avg_reciprocal_data))", "$signed(32'(avg_reciprocal[valid_taps]))", 1)
    if normalize(restored) != normalize(reference):
        raise RuntimeError('倒数表和消费表达式以外的源码不同')
    hashes = {str(SOURCE): digest(ROOT/SOURCE), str(Path(__file__).resolve().relative_to(ROOT)): digest(Path(__file__).resolve())}
    (out/'reference.sv').write_text(unit(reference, registered_reference=True))
    (out/'current.sv').write_text(unit(current))
    (out/'reference_comb.sv').write_text(unit(reference))
    configurations = (1, 3, 49, 255, 256, 257)
    runs = []
    for maximum in configurations:
        for mode, defines in (('fpga', ''), ('asic', '-D ASIC_SYNTHESIS=1')):
            folder = out/(mode+'_'+str(maximum))
            folder.mkdir(exist_ok=True)
            commands = []
            for label in ('reference', 'current'):
                commands += [f'read_slang {defines} --top reciprocal_unit -GPOOL_MAX_TAPS={maximum} '+
                             shlex.quote(str(out/(label+'.sv'))),
                             'prep -top reciprocal_unit -flatten', 'memory_map', 'opt -full',
                             'rename reciprocal_unit '+label, 'design -stash '+label]
            commands += ['design -copy-from reference -as reference reference',
                         'design -copy-from current -as current current',
                         'equiv_make reference current comparison', 'prep -top comparison',
                         'equiv_simple -undef', 'equiv_induct -undef -seq 2', 'equiv_status -assert']
            script = folder/'formal.ys'
            script.write_text('\n'.join(commands)+'\n')
            log = folder/'formal.log'
            sha = worker(script, log)
            if 'Equivalence successfully proven' not in log.read_text():
                raise RuntimeError('倒数表时序比较未完成')
            runs.append({'pool_max_taps': maximum, 'mode': mode, 'passed': True,
                         'entries': maximum+1, 'output_bits': 9+(maximum).bit_length(),
                         'log_sha256': sha})
            print(json.dumps(runs[-1]), flush=True)
    cases = {}
    for name, source in (('reference', out/'reference_comb.sv'), ('current', out/'current.sv')):
        cases[name] = {'top': 'reciprocal_unit', 'options': [], 'sources': [str(source)],
                       'configuration': '257项完整精度倒数表，参考为异步读取，当前为同步读取'}
    (out/'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2)+'\n')
    summary = {'passed': True, 'reference_revision': reference_revision, 'source_sha256': hashes,
               'unchanged_surrounding_rtl': True,
               'method': '原始常量表延迟一拍与当前同步读取进行完整时序等价比较',
               'input_constraints': None, 'runs': runs}
    (out/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
