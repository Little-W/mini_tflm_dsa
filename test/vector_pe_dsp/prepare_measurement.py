#!/usr/bin/env python3
"""固定八路寄存算术单元的资源测量输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference-rev',default='d9abf98')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    source = ROOT / 'rtl/npu/conv/vector_pe.sv'
    snapshot = out / 'vector_pe.sv'
    snapshot.write_bytes(source.read_bytes())
    cases = {}
    for label,dsp in [('reference',False),('registered',True)]:
        path = out / (label + '.sv')
        path.write_text(f'''module pe_bank (
          input logic clk, i_en,
          input logic [2:0] i_op,
          input logic [7:0][15:0] i_a, i_b,
          input logic [7:0][31:0] i_acc,
          output logic [7:0][31:0] o_result
        );
          for (genvar lane = 0; lane < 8; lane++) begin : g_lane
            registered_vector_pe #(.p_use_dsp(1'b{int(dsp)})) u_pe (
              .clk(clk), .i_en(i_en), .i_op(i_op), .i_a(i_a[lane]), .i_b(i_b[lane]),
              .i_acc(i_acc[lane]), .o_result(o_result[lane])
            );
          end
        endmodule
        ''')
        cases[label] = {'top':'pe_bank','options':['-D','SYNTHESIS=1'],
                        'sources':[str(snapshot),str(path)],
                        'configuration':'8 PE, signed INT16 inputs and INT32 accumulators, independent operand enable'}
    dependencies = ['conv_im2col_pkg.sv','vector_engine_pkg.sv',
                    'vector_writeback.sv','vector_round_shift.sv','vector_scalar_multiplier.sv',
                    'vector_softmax.sv','vector_quant_params.sv']
    dependencies = [ROOT/'rtl/npu/conv'/name for name in dependencies]
    source_hashes = {}
    for label in ['reference','registered']:
        selected = []
        for name in ['vector_pe.sv','vector_engine.sv','vector_config_check.sv']:
            relative = 'rtl/npu/conv/' + name
            data = (read_rtl_source(args.reference_rev+':'+relative, cwd=ROOT)
                    if label == 'reference' else (ROOT/relative).read_bytes())
            path = out/(label+'_'+name)
            path.write_bytes(data)
            selected.append(path)
            source_hashes[label+'/'+relative] = hashlib.sha256(data).hexdigest()
        cases['vector_'+label] = {'top':'vector_engine',
                                'options':['-D','SYNTHESIS=1','-GTILE=16','-GBUS_WIDTH=64','-GPE_COUNT=8'],
                                'sources':[str(p) for p in dependencies+selected],
                                'configuration':'Production vector engine: TILE16 PE8 BUS64 all public outputs'}
    (out / 'cases.json').write_text(json.dumps(cases,indent=2) + '\n')
    manifest = {'reference_rev':args.reference_rev,
                'source_sha256':source_hashes,
                'dependencies_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                                       for p in dependencies+[ROOT/'rtl/common/regfile.v']}}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest))


if __name__ == '__main__':
    main()
