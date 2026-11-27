#!/usr/bin/env python3
"""证明描述符算术及准备元数据的寄存移动关系。"""
from pathlib import Path
from source_sections import read_module, dependencies
import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-root', type=Path, default=ROOT)
parser.add_argument('--out', type=Path, default=ROOT/'build/frontend_pipeline/arithmetic_formal')
args = parser.parse_args()
SOURCE, rtl = read_module(args.source_root, 'descriptor')
OUT = args.out.resolve()
OUT.mkdir(parents=True, exist_ok=True)
unit = '''module comparison #(parameter int W=35)(
  input logic [W-1:0] a,b,
  input logic carry,
  output logic equivalent
);
  logic [W-1:0] grouped, arithmetic;
  logic unused_carry;
  parallel_prefix_add #(.p_width(W), .p_group_width(4), .p_preserve_groups(1'b1)) u_reference (
    .i_a(a), .i_b(b), .i_carry(carry), .o_sum(grouped), .o_carry(unused_carry)
  );
  assign arithmetic = a + b + W'(carry);
  assign equivalent = grouped == arithmetic;
endmodule
'''
(OUT / 'arithmetic.sv').write_text(unit)
start = rtl.index('  if (TILE_COUNT_W < 32) begin : g_prepared_active_columns')
start = rtl.index('\n', start) + 1
end = rtl.index('  end else begin : g_prepared_active_columns_wide', start)
active = rtl[start:end]
metadata = '''module comparison #(parameter int TILE_COUNT_W=5)(
  input logic clk,cfg_accept,tile_valid,consume,
  input logic [31:0] cfg_reduction,input_reduction,
  input logic [15:0] cfg_group,
  input logic [TILE_COUNT_W-1:0] input_columns,
  output logic equivalent
);
  logic valid_q;
  logic [31:0] reduction_len,descriptor_reduction;
  logic [15:0] group_c;
  logic [TILE_COUNT_W-1:0] descriptor_columns,prepared_active_columns,reference_active;
  logic [32:0] reference_next,reference_skip;
  logic [31:0] incoming_remaining;
  logic [TILE_COUNT_W-1:0] incoming_active;
  logic accept,configure;
  assign configure=cfg_accept&&!valid_q;
  assign accept=tile_valid&&!configure&&(!valid_q||consume);
  assign incoming_remaining=reduction_len-input_reduction;
  assign incoming_active=incoming_remaining<32'(input_columns) ?
      TILE_COUNT_W'(incoming_remaining):input_columns;
  always_ff @(posedge clk) begin
    if(configure)begin reduction_len<=cfg_reduction;group_c<=cfg_group;end
    if(accept)begin
      valid_q<=1'b1;
      descriptor_reduction<=input_reduction;
      descriptor_columns<=input_columns;
      reference_next<={1'b0,input_reduction}+{17'd0,group_c};
      reference_skip<={1'b0,input_reduction}+{16'd0,group_c,1'b0};
      reference_active<=incoming_active;
    end else if(consume)valid_q<=1'b0;
  end
ACTIVE
  assign equivalent=!valid_q ||
    (reference_next=={1'b0,descriptor_reduction}+{17'd0,group_c} &&
     reference_skip=={1'b0,descriptor_reduction}+{16'd0,group_c,1'b0} &&
     reference_active==prepared_active_columns);
endmodule
'''.replace('ACTIVE', active)
(OUT / 'metadata.sv').write_text(metadata)
arithmetic_sources = dependencies(args.source_root, [OUT/'arithmetic.sv'])
metadata_sources = dependencies(args.source_root, [OUT/'metadata.sv'])
cases = []
def run(name, code):
    script = OUT / (name + '.ys')
    log = OUT / (name + '.log')
    script.write_text(code)
    with log.open('w') as handle:
        result = subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
            '--worker', str(script)], cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT)
    assert result.returncode == 0, log
    cases.append({'name':name,'passed':True,
                  'script_sha256':hashlib.sha256(script.read_bytes()).hexdigest(),
                  'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
for width in (32,33,35):
    run('arithmetic_'+str(width),
        f'read_slang --top comparison -GW={width} '+shlex.join(map(str,arithmetic_sources))+'\n'
        'prep -top comparison -flatten\nsat -verify -prove equivalent 1\n')
for width in (1,3,5,8,16,31):
    run('metadata_'+str(width),
        f'read_slang --top comparison -DSYNTHESIS=1 -GTILE_COUNT_W={width} '+shlex.join(map(str,
            metadata_sources))+
        '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
        'prep -top comparison -flatten\nsat -seq 6 -set-init-zero -verify -prove equivalent 1\n')
summary={'passed':True,'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
         'cases':cases}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({'passed':True,'cases':len(cases),'source_sha256':summary['source_sha256']}))
