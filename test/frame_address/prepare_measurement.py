#!/usr/bin/env python3
"""固定三个帧地址表达式与共享准备单元的独立综合输入。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='745d72da')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'rtl/npu/top/frame_address_prepare.sv'
    candidate = out / source.name
    candidate.write_bytes(source.read_bytes())
    original = read_rtl_source(args.reference_rev + ':rtl/npu/top/npu_top.sv', cwd=ROOT, text=True)
    function = re.search(r'function automatic logic \[REG_WIDTH-1:0\] operand_frame_offset\(.*?endfunction', original, re.S)[0]
    ports = re.search(r'\) \(\n(.*?)\n\);', source.read_text(), re.S)[1]
    reference = out / 'frame_address_reference.sv'
    reference.write_text('module frame_address_reference(\n' + ports + '\n);\n'
        'localparam int REG_WIDTH=32,SIZE=16,SIZE_SHIFT=4;\n' + function + '\n' + '''
    assign o_start_rdy=1'b1;
    assign o_result_vld=i_start;
    assign o_ia_base=i_ia_base+operand_frame_offset(i_p0,i_q0,i_ia_stride,i_total_depth,i_ia_packed,i_ia_s16);
    assign o_weight_base=i_weight_base+operand_frame_offset(i_column,i_q0,i_weight_stride,i_total_depth,i_weight_packed,i_weight_s16);
    assign o_dst_base=i_dst_base+(i_is_mode ? i_column : i_p0)*i_dst_stride+((i_is_mode ? i_p0 : i_column)<<i_output_s16);
endmodule
''')
    cases = {}
    for label, path, top in [('reference', reference, 'frame_address_reference'),
                             ('candidate', candidate, 'frame_address_prepare')]:
        cases[label] = {'top': top, 'options': ['-D', 'SYNTHESIS=1'], 'sources': [str(path)],
                        'configuration': 'Three complete 32-bit frame addresses, tile16, all layout and precision modes'}
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')
    summary = {'reference_revision': args.reference_rev,
               'reference_top_sha256': hashlib.sha256(original.encode()).hexdigest(),
               'input_sha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (reference,candidate)}}
    (out / 'input_manifest.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
