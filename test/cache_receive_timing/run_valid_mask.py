#!/usr/bin/env python3
"""证明六个实际有效位读取端口的填充屏蔽关系。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex

from run import execute
from support import check_sources, digest, prepare_inputs


def model(label, source):
    first = source.index('    for (genvar read_port = 0; read_port < 6; read_port++) begin : g_valid_read')
    end = source.index('    assign valid_lookup[metadata_way]', first)
    expressions = source[first:end]
    # 此处只证明填充屏蔽，读取结果及对应地址均为自由输入。
    # 查询有效位的保存和同拍写入转发由完整缓存证明检查。
    expressions = expressions.replace('valid_o_rd_data[read_port][0]',
                                      'valid_read_value[read_port]')
    expressions = expressions.replace('valid_i_rd_addr[read_port]',
                                      'valid_match_address[read_port]')
    return f'''module {label} #(
    parameter int SI=7, WI=1, metadata_way=0
) (
    input logic configured, clearing,
    input logic [1:0] fill_state,
    input logic [WI-1:0] fill_way,
    input logic [SI-1:0] fill_set,
    input logic [5:0][SI-1:0] valid_match_address,
    input logic [5:0] valid_read_value,
    output logic [5:0] valid_active
);
    localparam logic [1:0] F_IDLE=0;
{expressions}
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    _, paths, _, manifest = prepare_inputs(out, args.reference, args.candidate)
    models = {}
    for label, path in paths.items():
        target = out / (label + '_valid_mask.sv')
        target.write_text(model(label, path.read_text()))
        models[label] = target
    rows = []
    for index_width in range(1, 33):
        for way_width, way in ((1, 0), (3, 5)):
            name = f'si{index_width}_wi{way_width}'
            script, log = out / (name + '.ys'), out / (name + '.log')
            commands = []
            for label, path in models.items():
                commands += [f'read_slang --top {label} -GSI={index_width} -GWI={way_width} '
                             f'-Gmetadata_way={way} ' + shlex.quote(str(path)),
                             f'prep -top {label} -flatten', f'design -stash {label}']
            commands += ['design -copy-from reference -as reference reference',
                         'design -copy-from current -as current current',
                         'rename -hide reference/w:* current/w:*',
                         'equiv_make reference current comparison', 'hierarchy -top comparison',
                         'equiv_simple', 'equiv_status -assert']
            script.write_text('\n'.join(commands) + '\n')
            execute(script, log, 'Equivalence successfully proven')
            rows.append({'index_width': index_width, 'way_width': way_width, 'way': way,
                         'passed': True, 'log_sha256': digest(log)})
            print(name, flush=True)
    check_sources(manifest)
    report = {'passed': True, 'inputs': manifest, 'input_assumptions': [],
              'scope': 'Six actual metadata valid-read expressions for index widths 1 through 32 and way widths 1/3',
              'profiles': rows}
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(out / 'summary.json')


if __name__ == '__main__':
    main()
