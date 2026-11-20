#!/usr/bin/env python3
"""证明复用幂次检查的有效位宽覆盖全部容量与输出合并使用条件。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source

SOURCE = 'rtl/npu/top/npu_top.sv'


def fragment(text, module):
    start = text.index('// 相同配置值共用幂次检查')
    end = text.index('logic [REG_WIDTH-1:0] w_reuse_shape_i_value;', start)
    shape = text[start:end]
    admission = re.search(r'wire ext_r_legal\s*=.*?;', text, re.S).group(0)
    coalesce_values = [value for value in re.findall(r'oa_is_coalesce_q\s*<=\s*(.*?);', text, re.S)
                       if 'ia_reuse_shape_o_valid' in value]
    assert len(coalesce_values) == 1
    coalesce = coalesce_values[0]
    ws_values = [value for value in re.findall(r'oa_ws_coalesce_q\s*<=\s*(.*?);', text, re.S)
                 if 'SIZE' in value]
    assert len(ws_values) == 1
    return f'''module {module} #(
        parameter int REG_WIDTH=32, IA_REUSE_W=7, SIZE=16, ENABLE_IS_MODE=1, OA_FIFO_BANKS=64
    ) (
        input logic [REG_WIDTH-1:0] cfg_ia_reuse_eff_s2, cfg_k_s2, cfg_m_s2,
        input logic [REG_WIDTH-1:0] dst_base, dst_row_stride_b,
        input logic [31:0] active_ia_cache_blocks,
        input logic [4:0] oa_chunk_cols_pre,
        input logic cfg_compact_s2, cfg_mode_s2, cfg_16x8_s2,
        output logic legal, coalesce, ws_coalesce
    );
    {shape}
    wire [IA_REUSE_W-1:0] ext_r_small = cfg_ia_reuse_eff_s2[IA_REUSE_W-1:0];
    {admission}
    assign legal = ext_r_legal;
    assign coalesce = {coalesce};
    assign ws_coalesce = {ws_values[0]};
    endmodule
    '''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='2b829a62')
    parser.add_argument('--synthesis', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = read_rtl_source(f'{args.reference}:{SOURCE}', text=True)
    current = (ROOT / SOURCE).read_text()
    sources = []
    for name, text in (('reference', original), ('current', current)):
        path = out / f'{name}.sv'
        path.write_text(fragment(text, name))
        sources.append(path)
    parameters = [(reg, width) for reg in (16, 32) for width in (1, 2, 4, 5, 6, 7, 8, 9)]
    results = []
    for reg, width in parameters:
        script = out / f'r{reg}_w{width}.ys'
        script.write_text('read_slang --top reference ' + f'-GREG_WIDTH={reg} -GIA_REUSE_W={width} ' +
            str(sources[0]) + ' ' + str(ROOT / 'rtl/common/onehot_check.sv') + '\n'
            'prep -top reference -flatten\ndesign -stash reference\n' +
            'read_slang --top current ' + f'-GREG_WIDTH={reg} -GIA_REUSE_W={width} ' +
            str(sources[1]) + ' ' + str(ROOT / 'rtl/common/onehot_check.sv') + '\n'
            'prep -top current -flatten\ndesign -stash current\n'
            'design -copy-from reference -as reference reference\n'
            'design -copy-from current -as current current\n'
            'miter -equiv -flatten reference current proof\n'
            'prep -top proof\nsat -verify -prove trigger 0 -set-def-inputs\n')
        log = script.with_suffix('.log')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
        assert 'SUCCESS!' in log.read_text()
        results.append({'register_width': reg, 'reuse_width': width, 'passed': True,
                        'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
    assert current == (ROOT / SOURCE).read_text()
    report = {'passed': True, 'reference': args.reference, 'inputs_constrained': False,
              'checked_conditions': ['ext_r_legal', 'oa_is_coalesce_q', 'oa_ws_coalesce_q'], 'profiles': results,
              'source_sha256': hashlib.sha256(current.encode()).hexdigest()}
    if args.synthesis:
        cases = {label: {
            'top': label,
            'sources': [str(path), 'rtl/common/onehot_check.sv'],
            'options': ['-D', 'XILINX_FPGA=1', '-GREG_WIDTH=32', '-GIA_REUSE_W=7'],
            'configuration': '32位配置及7位有效复用数量',
        } for label, path in zip(('reference', 'current'), sources)}
        config = out / 'cases.json'
        config.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--case-config', str(config), '--cases', 'reference', 'current',
                        '--out', str(out / 'synthesis')], cwd=ROOT, check=True)
        report['synthesis'] = json.loads((out / 'synthesis/summary.json').read_text())
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'profiles': len(results)}), flush=True)


if __name__ == '__main__':
    main()
