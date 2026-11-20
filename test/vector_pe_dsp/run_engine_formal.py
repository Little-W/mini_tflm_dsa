#!/usr/bin/env python3
"""比较实际向量接入源码的操作数、独立操作码及所有 PE 结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]


def normalized(source):
    source = re.sub(r'`default_nettype\s+\w+','',source)
    source = re.sub(r'/\*.*?\*/|//[^\n]*','',source,flags=re.S)
    return re.sub(r'\s+','',source)


def sections(source):
    marker = '  assign pe_operand_en ='
    first = source.index(marker if marker in source else
                         '  for (genvar lane=0;lane<PE_COUNT;lane++) begin : g_operand_register')
    end = source.index('  // Channel banks provide',first)
    operand = source[first:end]
    outside = source[:first]+source[end:]
    first = outside.rfind('  for (genvar',0,outside.index('begin : g_pe'))
    end = outside.index('  wire signed [7:0] add_first_lhs',first)
    pe = outside[first:end]
    outside = outside[:first]+outside[end:]
    outside = outside.replace('  logic signed [15:0] pe_a_q [PE_COUNT],pe_b_q [PE_COUNT];\n','')
    outside = outside.replace('  logic signed [31:0] pe_acc_q [PE_COUNT];\n','')
    outside = outside.replace('  logic pe_operand_en;\n','')
    return operand,pe,normalized(outside)


def wrapper(source,tile,pes):
    operand,pe,_ = sections(source)
    state_type = re.search(r'typedef enum logic \[5:0\].*?state_t;',source,re.S)[0]
    candidate = 'registered_vector_pe u_pe' in pe
    values = (['g_pe[lane].u_pe.operand_a_q','g_pe[lane].u_pe.g_generic.operand_b_q',
               'g_pe[lane].u_pe.operand_acc_q'] if candidate else
              ['pe_a_q[lane]','pe_b_q[lane]','pe_acc_q[lane]'])
    declarations = ('logic pe_operand_en;' if candidate else
                    'logic signed [15:0] pe_a_q [PE_COUNT], pe_b_q [PE_COUNT];\n'
                    'logic signed [31:0] pe_acc_q [PE_COUNT];')
    return f'''module engine_pe_state #(
      parameter int TILE={tile}, PE_COUNT={pes},
      parameter int TILE_INDEX_W=$clog2(TILE+PE_COUNT+1), ACTIVE_COUNT_W=$clog2(TILE+1)
    ) (
      input logic clk, depthwise, writeback_busy,
      input logic [5:0] state,
      input vector_engine_pkg::vector_engine_cfg_t c,
      input logic [TILE_INDEX_W-1:0] compute_index,
      input logic [ACTIVE_COUNT_W-1:0] active,
      input logic [2:0] pe_op,
      input logic signed [15:0] input_lane [PE_COUNT], rhs_lane [PE_COUNT],
      input logic signed [7:0] weight_lane [PE_COUNT],
      input logic signed [31:0] accum_lane [PE_COUNT],
      output logic signed [31:0] pe_result [PE_COUNT],
      output logic [PE_COUNT*16-1:0] state_a,
      output logic [PE_COUNT*16-1:0] state_b,
      output logic [PE_COUNT*32-1:0] state_acc,
      output logic [2:0] state_op
    );
      import vector_engine_pkg::*;
      {state_type}
      logic signed [15:0] pe_a [PE_COUNT], pe_b [PE_COUNT];
      logic signed [31:0] pe_acc [PE_COUNT];
      {declarations}
      logic [2:0] pe_op_q;
      {operand}
      {pe}
      assign state_op = pe_op_q;
      for (genvar lane = 0; lane < PE_COUNT; lane++) begin : g_observe
        assign state_a[lane*16+:16] = {values[0]};
        assign state_b[lane*16+:16] = {values[1]};
        assign state_acc[lane*32+:32] = {values[2]};
      end
    endmodule
    '''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference-rev',default='d9abf98')
    parser.add_argument('--worker',type=Path)
    args = parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass('script '+shlex.quote(str(args.worker)))
        return
    out = args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    relative = 'rtl/npu/conv/vector_engine.sv'
    reference = read_rtl_source(args.reference_rev+':'+relative, cwd=ROOT, text=True)
    candidate = (ROOT/relative).read_text()
    assert sections(reference)[2] == sections(candidate)[2], 'Changes outside the PE register and connection blocks.'
    pe_source = ROOT/'rtl/npu/conv/vector_pe.sv'
    previous_pe = read_rtl_source(args.reference_rev+':rtl/npu/conv/vector_pe.sv', cwd=ROOT, text=True)
    assert normalized(previous_pe) == normalized(pe_source.read_text().split('endmodule',1)[0]+'endmodule')
    dependencies = [ROOT/'rtl/npu/conv/conv_im2col_pkg.sv',ROOT/'rtl/npu/conv/vector_engine_pkg.sv',pe_source]
    summary = {'reference_rev':args.reference_rev,'reference_sha256':hashlib.sha256(reference.encode()).hexdigest(),
               'source_sha256':hashlib.sha256(candidate.encode()).hexdigest(),
               'pe_sha256':hashlib.sha256(pe_source.read_bytes()).hexdigest(),
               'unchanged_legacy_pe':True,'unchanged_outside_register_connection':True,
               'input_constraints':None,'runs':[]}
    for tile,pes in [(1,1),(3,2),(16,8),(32,16)]:
        folder = out/f'tile{tile}_pe{pes}'
        folder.mkdir(exist_ok=True)
        commands = []
        for label,source in [('reference',reference),('candidate',candidate)]:
            path = folder/(label+'.sv')
            path.write_text(wrapper(source,tile,pes))
            commands += ['read_slang --top engine_pe_state -D ASIC_SYNTHESIS=1 '+
                         ' '.join(shlex.quote(str(p)) for p in dependencies+[path]),
                         'prep -top engine_pe_state -flatten','memory_map','opt -full','wreduce','opt -full',
                         'rename engine_pe_state '+label,'design -stash '+label]
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from candidate -as candidate candidate',
                     'equiv_make reference candidate comparison','hierarchy -top comparison',
                     'equiv_struct -fwd -icells','equiv_simple','equiv_induct -seq 2','equiv_status -assert']
        script = folder/'run.ys'
        script.write_text('\n'.join(commands)+'\n')
        with (folder/'formal.log').open('w') as log:
            result = subprocess.run([sys.executable,__file__,'--out',str(out),'--worker',str(script)],
                                    stdout=log,stderr=subprocess.STDOUT)
        log = (folder/'formal.log').read_text()
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven',log)
        record = {'tile':tile,'pe_count':pes,'compared_operand_state_bits':pes*64+3,
                  'equivalent_bits':int(match[1]) if match else None,
                  'passed':result.returncode==0 and 'Equivalence successfully proven!' in log}
        summary['runs'].append(record)
        print(json.dumps(record),flush=True)
        if not record['passed']:
            raise RuntimeError(log[-8000:])
    summary['passed'] = True
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')


if __name__ == '__main__':
    main()
