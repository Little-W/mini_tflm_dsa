#!/usr/bin/env python3
"""验证配置、描述符接收和运行错误的完整状态选择。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "test"))
from reference_sources import read_reference_file, resolve_reference
SOURCE = Path('rtl/npu/conv/conv_im2col_frontend.sv')
PACKAGE = Path('rtl/npu/conv/conv_im2col_frontend_pkg.sv')
FLAGS = ['i_error', 'i_configuration_complete', 'i_configuration_ok', 'i_cfg_fire',
         'i_basic_valid', 'i_tile_commit', 'i_tile_invalid', 'i_stream_error', 'i_stream_accept']


def sha(data):
    return hashlib.sha256(data).hexdigest()


def reference_projection(source):
    first = source.index('      // 配置、描述符提交与各运行状态互斥选择')
    first = source.index("      unique case (1'b1)", first)
    block = source[first:source.index('      endcase', first)]
    pattern = r'(?m)^ {8}((?:state\[|tile_commit\b|stream_response_error\b|stream_operation_accept\b|default\b|\()[^:;]*?):'
    matches = list(re.finditer(pattern, block))
    if len(matches) != 30:
        raise ValueError('Unexpected state branch structure')
    branches, assigned = [], {}
    for index, match in enumerate(matches):
        key = match.group(1)
        body = block[match.end():matches[index+1].start() if index+1 < len(matches) else len(block)]
        updates = re.findall(r'\b(error|tile_error)\s*<=\s*([^;]+);', body)
        assigned[key] = updates
        if updates:
            if key == 'tile_commit':
                assert re.search(r'if \(committing_tile.invalid\)', body)
                assert updates == [('tile_error', '1'), ('error', '1')]
                statement = "if(i_tile_invalid)begin expected_error=1'b1;expected_tile_error=1'b1;end"
            else:
                statement = 'begin '+' '.join('expected_'+name+'='+value+';' for name, value in updates)+' end'
        else:
            statement = ';'
        key = key.replace('(cfg_valid && cfg_ready)', 'i_cfg_fire').replace('tile_commit', 'i_tile_commit')
        key = key.replace('stream_response_error', 'i_stream_error').replace('stream_operation_accept', 'i_stream_accept').replace('state[', 'i_state[')
        statement = statement.replace('cfg_basic_valid', 'i_basic_valid')
        branches.append(key+': '+statement)
    assert {name for name, values in assigned.items() if values} == {
        '(cfg_valid && cfg_ready)', 'tile_commit', 'stream_response_error', 'default'}
    assert assigned['(cfg_valid && cfg_ready)'] == [('error', '!cfg_basic_valid')]
    assert assigned['stream_response_error'] == [('error', '1'), ('tile_error', '1')]
    assert assigned['default'] == [('error', '1')]
    assert re.search(r'if \(cfg_prepare_phase==4\) begin\s*configured<=cfg_ok;error<=!cfg_ok;', source)
    return 'always @(' + ' or '.join(['i_state', *FLAGS]) + ') begin\n' + ''' expected_error=i_error;expected_tile_error=1'b0;
 if(i_configuration_complete)expected_error=!i_configuration_ok;
 case(1'b1)
'''+ '\n'.join(branches)+'\n endcase\nend\n'


def model(current, reference):
    modules = []
    for name in ['conv_im2col_error_select', 'conv_im2col_error_operation_select', 'conv_im2col_error_update']:
        found = re.search(r'\bmodule '+name+r'\b.*?endmodule', current, re.S)
        if found is None:
            raise ValueError(name)
        modules.append(('(* keep_hierarchy = "yes" *)\n' if name.endswith('_select') else '') + found.group())
    assert len(re.findall(r'\berror\s*<=', current)) == 2
    assert len(re.findall(r'\btile_error\s*<=', current)) == 2
    return '\n'.join(modules)+'\nmodule proof(input logic[26:0]i_state,\n'+',\n'.join('input logic '+name for name in FLAGS)+''',
 output logic o_error,o_tile_error,expected_error,expected_tile_error,
 output logic error_equal,tile_error_equal
);
 import conv_im2col_frontend_pkg::*;
 conv_im2col_error_update dut(.*);
'''+reference_projection(reference)+'''
 assign error_equal=o_error===expected_error;
 assign tile_error_equal=o_tile_error===expected_tile_error;
endmodule
'''


def bench():
    checks=4**len(FLAGS)+72
    controls=','.join(FLAGS)
    return f'''module tb;
 logic[26:0]i_state;
 {' '.join('logic '+name+';' for name in FLAGS)}
 logic o_error,o_tile_error,expected_error,expected_tile_error,error_equal,tile_error_equal;
 logic[35:0]pattern,seen_x='0,seen_z='0;
 logic[8:0]control_value;
 integer value,digit;
 proof dut(.*);
 initial begin
  for(integer sample=0;sample<{checks};sample++)begin
   pattern={{$urandom,$urandom}};
   if(sample<{4**len(FLAGS)})begin
    value=sample;
    for(integer bit_index=0;bit_index<9;bit_index++)begin
     digit=value%4;value=value/4;
     case(digit)
      0:control_value[bit_index]=1'b0;
      1:control_value[bit_index]=1'b1;
      2:control_value[bit_index]=1'bx;
      3:control_value[bit_index]=1'bz;
     endcase
    end
    pattern[8:0]=control_value;
    case(sample%32)
     0:pattern[35:9]='0;
     28:pattern[35:9]='1;
     29:begin end
     30:pattern[35:9]=(27'b1<<((sample/32)%27))|(27'b1<<((sample/1024)%27));
     31:begin pattern[35:9]='0;pattern[9+(sample/32)%27]=sample[10]?1'bx:1'bz;end
     default:pattern[35:9]=27'b1<<((sample%32)-1);
    endcase
   end else pattern[(sample-{4**len(FLAGS)})/2]=(sample%2)?1'bz:1'bx;
   {{i_state,{controls}}}=pattern;
   for(integer bit_index=0;bit_index<36;bit_index++)begin
    if(pattern[bit_index]===1'bx)seen_x[bit_index]=1'b1;
    if(pattern[bit_index]===1'bz)seen_z[bit_index]=1'b1;
   end
   #1;
   if(error_equal!==1'b1||tile_error_equal!==1'b1)
    $fatal(1,"Error selection mismatch sample=%0d flags=%b state=%b actual=%b%b expected=%b%b",sample,{{{controls}}},i_state,o_tile_error,o_error,expected_tile_error,expected_error);
  end
  if(!(&seen_x)||!(&seen_z))$fatal(1,"Input X/Z coverage incomplete");
  $display("ERROR_SELECTION_PASS checks={checks}");$finish;
 end
endmodule
''', checks


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--reference-root',type=Path)
    parser.add_argument('--reference-ref',default='f1910d02')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();root=args.source_root.resolve();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    inputs={path:(root/path).read_bytes() for path in [SOURCE,PACKAGE]}
    if args.reference_root:
        reference=(args.reference_root.resolve()/SOURCE).read_bytes();commit=None
    else:
        commit=resolve_reference(root,args.reference_ref)
        reference=read_reference_file(root,commit,SOURCE)
    generated=out/'model.sv';generated.write_text(model(inputs[SOURCE].decode(),reference.decode()))
    (out/'reference.sv').write_bytes(reference)
    script=out/'proof.ys';script.write_text('read_slang --top proof '+shlex.join(map(str,[root/PACKAGE,generated]))+
        '\nprep -top proof -flatten\ncheck -assert\n'+''.join('sat -verify -prove '+name+' 1 -show-inputs -show-outputs\n' for name in ['error_equal','tile_error_equal']))
    log=out/'proof.log'
    with log.open('w') as handle:
        subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],stdout=handle,stderr=subprocess.STDOUT,check=True,timeout=300)
    assert log.read_text().count('SAT proof finished - no model found: SUCCESS!')==2
    tb,checks=bench();(out/'tb.sv').write_text(tb);binary=out/'simulation.vvp'
    with (out/'build.log').open('w') as handle:
        subprocess.run([shutil.which('iverilog') or 'iverilog','-g2012','-s','tb','-o',str(binary),str(root/PACKAGE),str(generated),str(out/'tb.sv')],stdout=handle,stderr=subprocess.STDOUT,check=True)
    started=time.monotonic();run_log=out/'four_state.log'
    with run_log.open('w') as handle:
        subprocess.run([shutil.which('vvp') or 'vvp',str(binary)],stdout=handle,stderr=subprocess.STDOUT,check=True,timeout=300)
    assert f'PASS checks={checks}' in run_log.read_text();binary.unlink()
    assert all(data==(root/path).read_bytes() for path,data in inputs.items()),'Production source changed'
    report={'passed':True,'source_sha256':{str(path):sha(data) for path,data in inputs.items()},
        'reference_commit':commit,'reference_sha256':{str(SOURCE):sha(reference)},
        'formal_cases':2,'four_state_checks':checks,'control_combinations':4**len(FLAGS),
        'state_patterns':['zero','each_single_state','all_states','multiple_states','arbitrary','each_bit_x_z'],
        'input_bits_with_x_z':36,'simulation_seconds':time.monotonic()-started,
        'logs_sha256':{path.name:sha(path.read_bytes()) for path in [log,run_log]}}
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print('ERROR_SELECTION_PASS',flush=True)


if __name__=='__main__':main()
