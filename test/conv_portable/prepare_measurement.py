#!/usr/bin/env python3
"""生成普通卷积算术与向量引擎的可复现综合输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--pes', type=int, default=16)
    args = parser.parse_args()
    if args.pes < 1:
        parser.error('--pes must be positive')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    dependencies = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    wrapper = out/'pe_bank.sv'
    wrapper.write_text(f'''module pe_bank (
  input logic clk,i_en,
  input logic [2:0] i_op,
  input logic [{args.pes-1}:0][15:0] i_a,i_b,
  input logic [{args.pes-1}:0][31:0] i_acc,
  output logic [{args.pes-1}:0][31:0] o_result
);
  for(genvar lane=0;lane<{args.pes};lane++)begin:g_lane
    registered_vector_pe u_pe(
      .clk,.i_en,.i_op,.i_a(i_a[lane]),.i_b(i_b[lane]),.i_acc(i_acc[lane]),.o_result(o_result[lane]));
  end
endmodule
''')
    conv = ROOT/'rtl/npu/conv'
    cases = {}
    specs = {
        'pe_bank': ([wrapper, conv/'registered_vector_pe.sv'], [],
                    f'{args.pes} registered PEs, INT16 inputs, INT32 accumulators'),
        'vector_engine': ([conv/'vector_engine.sv'], ['-GTILE=16', '-GBUS_WIDTH=64', f'-GPE_COUNT={args.pes}'],
                          f'TILE16 BUS64 PE{args.pes}, complete vector engine'),
        'vector_reduce_alu': ([conv/'vector_reduce_alu.sv'], [], 'INT32 sum and extrema'),
        'vector_read_address_add': ([conv/'vector_read_address_add.sv'], [], '32+32+16-bit complete address sum'),
        'registered_multiplier_s32': ([conv/'registered_multiplier_s32.sv'], [], 'Full signed INT64 product, two enabled edges'),
    }
    hashes = {}
    for name, (seeds, options, configuration) in specs.items():
        sources = dependencies(seeds, ROOT)
        cases[name] = {'top': name, 'options': ['-D', 'SYNTHESIS=1', *options],
                       'sources': list(map(str, sources)), 'configuration': configuration}
        for path in sources:
            hashes[str(path)] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    (out/'cases.json').write_text(json.dumps(cases, indent=2)+'\n')
    (out/'manifest.json').write_text(json.dumps({'source_sha256': hashes, 'pes': args.pes}, indent=2)+'\n')
    print(json.dumps({'prepared': True, 'cases': list(cases), 'sources': len(hashes)}))


if __name__ == '__main__':
    main()
