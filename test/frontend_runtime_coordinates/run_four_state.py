#!/usr/bin/env python3
"""在完整运行寄存器上逐周期比较自由状态、四态控制及全部输出。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess

from run_formal import ROOT, SOURCE, REFERENCE, PARAMETERS, PROFILES, profile_name

MODES = {
    'generic': ['-USYNTHESIS', '-UXILINX_FPGA'],
    'synthesis': ['-DSYNTHESIS=1', '-UXILINX_FPGA'],
    'fpga': ['-USYNTHESIS', '-DXILINX_FPGA=1'],
    'fpga_synthesis': ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'],
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def port_declarations(source):
    result = []
    for line in source[:source.index('\n);')].splitlines():
        match = re.match(r'\s*(input|output)\s+(?:wire\s+)?(.+?)\s+(\w+)\s*,?\s*//', line)
        if match:
            result.append(match.groups())
    return result


def unroll_fixed_loops(source):
    # Icarus 接收常量索引的多维打包数组，固定循环按相同顺序展开。
    pattern = re.compile(r'for \(int (\w+) = 0; \1 < (\d+); \1\+\+\) begin\n(.*?)\n\s*end', re.S)
    def expand(match):
        return '\n'.join(re.sub(r'\b'+match[1]+r'\b', str(index), match[3])
                          for index in range(int(match[2])))
    return pattern.sub(expand, source)


def testbench(parameters, ports):
    inputs = [(kind, name) for direction, kind, name in ports if direction == 'input']
    outputs = [(kind, name) for direction, kind, name in ports if direction == 'output']
    declarations = '\n'.join('  '+kind.replace('conv_im2col_frontend_pkg::st_t', 'logic [26:0]')+
                              ' '+name+';' for kind, name in inputs)
    params = '\n'.join(f'  localparam integer {name} = {value};' for name, value in parameters.items())
    params += '\n  localparam integer p_prepared_tile_width = 458+2*p_coord_width+3*p_count_width+' \
              'p_slot_width+p_saved_group_lanes-p_word_shift;'
    instance_parameters = ','.join('.'+name+'('+name+')' for name in parameters)
    input_connections = ','.join('.'+name+'('+name+')' for kind, name in inputs)
    input_random = '\n'.join(f'    {name} = $bits({name})\'(random_vector($bits({name}), pattern));'
                             for kind, name in inputs if name not in ('clk', 'rst_n'))
    state_random = '\n'.join(f'    actual.{name} = $bits(actual.{name})\'(random_vector($bits(actual.{name}), pattern));\n'
                             f'    reference_model.{name} = actual.{name};' for kind, name in outputs)
    comparisons = '\n'.join(f'    if(actual.{name} !== reference_model.{name})\n'
        f'      $fatal(1,"runtime field={name} sample=%0d state=%b cfg=%b%b tile=%b error=%b accept=%b actual=%h reference=%h fast_valid=%b fast_coordinate=%h state_write=%b selected_write=%b state_data=%h selected_data=%h",'
        f'checks,i_state,i_cfg_valid,i_cfg_ready,i_tile_commit,i_stream_response_error,i_stream_operation_accept,'
        f'actual.{name},reference_model.{name},i_p_fast_valid,i_fast_coordinate,actual.state_coordinate_write,actual.coordinate_write,actual.state_coordinate_data,actual.coordinate_data);' for kind, name in outputs)
    return '''module tb;
  import conv_im2col_frontend_pkg::*;
'''+params+'\n'+declarations+'''
  integer random_state = 32'h573a6821;
  integer checks = 0;
  logic [31:0] choose_state;
  reference_runtime #('''+instance_parameters+') reference_model('+input_connections+''');
  conv_im2col_runtime_registers #('''+instance_parameters+') actual('+input_connections+''');

  function automatic logic value4(input integer value);
    case(value & 3)
      0:value4=1'b0;
      1:value4=1'b1;
      2:value4=1'bx;
      3:value4=1'bz;
    endcase
  endfunction
  function automatic logic [31:0] random_word;
    random_state=random_state^(random_state<<13);
    random_state=random_state^(random_state>>17);
    random_state=random_state^(random_state<<5);
    return random_state;
  endfunction
  function automatic logic [1023:0] random_vector(input integer width, input integer pattern);
    logic [1023:0] result;
    result='0;
    for(integer word_index=0;word_index<(width+31)/32;word_index++)
      result[32*word_index+:32]=random_word();
    case(pattern%32)
      0:result='0;
      1:result='1;
      2:result='x;
      3:result='z;
      4,5,6,7:result[(random_word()&32'h7fff_ffff)%width]=1'bx;
      8,9,10,11:result[(random_word()&32'h7fff_ffff)%width]=1'bz;
      default:;
    endcase
    return result;
  endfunction
  task automatic prepare(input integer pattern);
    clk=0;rst_n=1;
'''+input_random+'\n'+state_random+'''
  endtask
  task automatic compare;
    #1;
'''+comparisons+'''
    checks++;
  endtask
  task automatic tick;
    #1;clk=1;compare();#1;clk=0;
  endtask
  initial begin
    clk=0;rst_n=1;
    // 自由共有状态覆盖所有已保存字段，全部公开输出在同一边沿后比较。
    for(integer state_index=0;state_index<32;state_index++)begin
      for(integer controls=0;controls<1024;controls++)begin
        prepare(controls+state_index);
        if(state_index<27)i_state=27'(1)<<state_index;
        else case(state_index)
          27:i_state='0;
          28:i_state='1;
          29:begin i_state='x;i_state[$clog2(K_WAIT)]=1;end
          30:begin i_state='z;i_state[$clog2(P_WAIT)]=1;end
          31:begin i_state=K_DECODE|P_DECODE|P_WAIT;i_state[$clog2(P_HISTORY)]=1'bx;end
        endcase
        i_cfg_valid=value4(controls);i_cfg_ready=value4(controls>>2);
        i_tile_commit=value4(controls>>4);i_stream_response_error=value4(controls>>6);
        i_stream_operation_accept=value4(controls>>8);
        i_chunk_reaches_end=value4(controls>>4);i_tap_wrap=value4(controls>>6);
        i_row_wrap=value4(controls>>2);i_active_after_chunk=value4(controls>>6);
        i_p_fast_valid=value4(controls>>2);i_group_end_o_equal=value4(controls>>4);
        i_kernel_shape_o_valid=value4(controls>>8);
        tick();
      end
    end
    // 随机多位状态与控制逐位注入 X、Z，并包含异步复位的同时更新。
    for(integer sample=0;sample<16384;sample++)begin
      prepare(sample);
      i_state=27'(random_word());
      for(integer state_bit=0;state_bit<27;state_bit++)begin
        if(sample%8==0)i_state[state_bit]=value4(random_word());
      end
      i_cfg_valid=value4(random_word());i_cfg_ready=value4(random_word());
      i_tile_commit=value4(random_word());i_stream_response_error=value4(random_word());
      i_stream_operation_accept=value4(random_word());
      i_chunk_reaches_end=value4(random_word());i_tap_wrap=value4(random_word());
      i_row_wrap=value4(random_word());i_active_after_chunk=value4(random_word());
      i_p_fast_valid=value4(random_word());i_group_end_o_equal=value4(random_word());
      i_kernel_shape_o_valid=value4(random_word());
      if(sample%128==0)begin #1;rst_n=0;compare();end
      tick();
    end
    $display("RUNTIME_COORDINATE_FOUR_STATE_PASS checks=%0d",checks);$finish;
  end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default=REFERENCE)
    parser.add_argument('--mode', choices=tuple(MODES)+('all',), default='all')
    parser.add_argument('--profile')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = (ROOT/SOURCE).read_text()
    reference = out/'reference.sv'
    text = subprocess.check_output(['git','show',args.reference+':'+str(SOURCE)], cwd=ROOT, text=True)
    reference.write_text(unroll_fixed_loops(text).replace('module conv_im2col_runtime_registers', 'module reference_runtime', 1))
    current = out/'current.sv'
    current.write_text(unroll_fixed_loops(source))
    resolver = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))
    sources = resolver['with_dependencies']([reference, current], ROOT)
    files = resolver['input_files']([ROOT/SOURCE, *sources], ROOT)
    hashes = {str(path): digest(path) for path in files}
    ports = port_declarations(source)
    runs = []
    for values in (PROFILES[0], PROFILES[-1]):
        profile = profile_name(values)
        if args.profile and args.profile != profile:
            continue
        parameters = dict(zip(PARAMETERS, values))
        parameters.update(p_row_high_width=27, p_cache_sets=16, p_cache_ways=2)
        bench = out/(profile+'.sv')
        bench.write_text(testbench(parameters, ports))
        for mode, flags in MODES.items():
            if args.mode != 'all' and args.mode != mode:
                continue
            name = profile+'_'+mode
            binary, log = out/(name+'.vvp'), out/(name+'.log')
            with (out/(name+'_build.log')).open('w') as stream:
                subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-I'+str(ROOT/'include'),
                    *[flag for flag in flags if flag.startswith('-D')], '-o', str(binary), *map(str,sources), str(bench)],
                    cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
            with log.open('w') as stream:
                subprocess.run(['vvp', str(binary)], cwd=ROOT,
                    stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=360)
            match = re.search(r'RUNTIME_COORDINATE_FOUR_STATE_PASS checks=(\d+)', log.read_text())
            if not match:
                raise RuntimeError('完整寄存器四态比较未完成：'+name)
            row = dict(profile=profile, mode=mode, parameters=parameters,
                       passed=True, checks=int(match[1]), log_sha256=digest(log))
            runs.append(row)
            print(json.dumps(row), flush=True)
    if not runs or any(digest(path) != value for path, value in hashes.items()):
        raise RuntimeError('验证配置为空或运行期间源码发生变化')
    report = dict(passed=True, source_sha256=hashes, runner_sha256=digest(__file__),
                  public_outputs_compared=sum(direction=='output' for direction, _, _ in ports),
                  comparisons=sum(row['checks'] for row in runs), runs=runs)
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__ == '__main__':
    main()
