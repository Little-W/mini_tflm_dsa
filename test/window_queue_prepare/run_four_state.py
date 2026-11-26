#!/usr/bin/env python3
"""比较窗口队列在未知控制、数据及恢复过程中的全部公开输出和存储状态。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/dma/conv_window_queue.sv')
REFERENCE = '8a31b855'

INPUTS = [
    ('clk', ''), ('rst_n', ''), ('configure', ''), ('enable', ''),
    ('req_valid', ''), ('req_p0', '[31:0]'), ('req_q0', '[31:0]'), ('req_cols', '[31:0]'),
    ('req_tag', '[1:0]'), ('rsp_ready', ''), ('frontend_ready', ''),
    ('frontend_rsp_valid', ''), ('frontend_rsp_col', '[3:0]'),
    ('frontend_rsp_mask', '[7:0]'), ('frontend_rsp_last', ''), ('frontend_error', ''),
]
OUTPUTS = [
    ('req_ready', ''), ('rsp_valid', ''), ('rsp_tag', '[1:0]'), ('rsp_col', '[3:0]'),
    ('rsp_mask', '[7:0]'), ('rsp_last', ''), ('rsp_error', ''), ('busy', ''),
    ('frontend_valid', ''), ('frontend_active', ''), ('frontend_p0', '[31:0]'),
    ('frontend_q0', '[31:0]'), ('frontend_cols', '[31:0]'), ('frontend_cols_valid', ''),
    ('frontend_rsp_ready', ''),
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expand_fields(source):
    """为 Icarus 展开固定三次字段循环，保留原赋值操作和执行顺序。"""
    pattern = (r'for\s*\(int\s+field_index\s*=\s*0;\s*field_index\s*<\s*3;'
               r'\s*field_index\+\+\)\s*'
               r'(descriptor_prepared_(?:data|value)\[field_index\]\s*(?:<=|=).*?;)')
    source, count = re.subn(pattern, lambda match: '\n'.join(
        re.sub(r'\bfield_index\b', str(index), match[1]) for index in range(3)),
        source, flags=re.S)
    assert count == 1
    return source


def bench():
    lines = ['`timescale 1ns/1ps', 'module tb;',
             'logic signed [15:0] frontend_rsp_data[8];',
             'integer sample, phase, episode, checks=0;', 'logic unknown_value;']
    lines += [f'logic {width} {name};' for name, width in INPUTS]
    for label in ('reference', 'candidate'):
        lines += [f'logic {width} {label}_{name};' for name, width in OUTPUTS]
        lines += [f'logic signed [15:0] {label}_rsp_data[8];']
        ports = [f'.{name}({name})' for name, _ in INPUTS]
        ports += ['.frontend_rsp_data(frontend_rsp_data)']
        ports += [f'.{name}({label}_{name})' for name, _ in OUTPUTS]
        ports += [f'.rsp_data({label}_rsp_data)']
        lines += [f'queue_{label} #(.DEPTH(4),.WINDOW_LANES(8),.p_frontend_outstanding(3)) '
                  f'u_{label}('+','.join(ports)+');']
    expected = '{'+','.join('reference_'+name for name, _ in OUTPUTS)+'}'
    actual = '{'+','.join('candidate_'+name for name, _ in OUTPUTS)+'}'
    lines += ['task automatic check;',
              f'if ({expected} !== {actual}) $fatal(1,"公开输出不一致：sample=%0d",sample);',
              'for(integer lane=0;lane<8;lane++)',
              'if(reference_rsp_data[lane]!==candidate_rsp_data[lane]) '
              '$fatal(1,"响应数据不一致：sample=%0d lane=%0d",sample,lane);']
    for signal in ('count', 'head', 'tail', 'present', 'active_count', 'failed',
                   'descriptor_prepared', 'descriptor_prepared_data'):
        lines += [f'if(u_reference.{signal}!==u_candidate.{signal}) '
                  f'$fatal(1,"状态不一致：{signal} sample=%0d",sample);']
    lines += ['for(integer entry=0;entry<4;entry++)begin']
    for signal in ('tags', 'cols_valid'):
        lines += [f'if(u_reference.{signal}[entry]!==u_candidate.{signal}[entry]) '
                  f'$fatal(1,"存储状态不一致：{signal} sample=%0d",sample);']
    for field in range(3):
        name = f'g_descriptor[{field}].u_value.mem[entry]'
        lines += [f'if(u_reference.{name}!==u_candidate.{name}) '
                  f'$fatal(1,"描述符存储不一致：field={field} sample=%0d",sample);']
    lines += ['end', 'checks++;', 'endtask', '''
initial begin
  clk=0;
  for(sample=0;sample<65536;sample++)begin
    phase=sample%32;
    episode=sample/32;
    rst_n=1;configure=0;enable=1;req_valid=0;rsp_ready=0;frontend_ready=0;
    frontend_rsp_valid=0;frontend_rsp_last=0;frontend_error=0;
    req_p0=32'(sample*17+3);req_q0=32'(sample*31+7);req_cols=32'(1+sample%16);
    req_tag=2'(sample);frontend_rsp_col=4'(sample);frontend_rsp_mask=8'hff;
    for(integer lane=0;lane<8;lane++)frontend_rsp_data[lane]=16'($urandom);
    if(phase==0)rst_n=0;
    else if(phase<=4)req_valid=1;
    else if(phase==5)frontend_ready=1;
    else if(phase==6)begin
      req_valid=1;frontend_ready=1;rsp_ready=1;frontend_rsp_valid=1;frontend_rsp_last=1;
      unknown_value=episode[0] ? 1'bx : 1'bz;
      case((episode/2)%9)
        0:rst_n=unknown_value;
        1:configure=unknown_value;
        2:enable=unknown_value;
        3:req_valid=unknown_value;
        4:rsp_ready=unknown_value;
        5:frontend_ready=unknown_value;
        6:frontend_rsp_valid=unknown_value;
        7:frontend_rsp_last=unknown_value;
        8:frontend_error=unknown_value;
      endcase
    end else if(phase>=8)begin
      req_valid=1'($urandom);frontend_ready=1'($urandom);rsp_ready=1'($urandom);
      frontend_rsp_valid=1'($urandom);frontend_rsp_last=1'($urandom);
      frontend_error=($urandom%43)==0;
      configure=($urandom%29)==0;
      if(phase==12 && episode%5==0)configure=1;
      if(phase==20 && episode%7==0)rst_n=0;
    end
    if(episode%7==0)req_q0[3]=1'bx;
    if(episode%11==0)req_p0[17]=1'bz;
    #1;check();clk=1;#1;check();clk=0;#1;
  end
  $display("PASS cycles=65536 observations=%0d",checks);
  $finish;
end
endmodule
''']
    return '\n'.join(lines)+'\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    snapshots = []
    for label in ('reference', 'candidate'):
        source = (subprocess.check_output(['git', 'show', REFERENCE+':'+str(SOURCE)],
                                         cwd=ROOT, text=True)
                  if label == 'reference' else (ROOT/SOURCE).read_text())
        source = re.sub(r'\bmodule conv_window_queue\b', 'module queue_'+label, source, count=1)
        source = expand_fields(source)
        path = out/(label+'.sv')
        path.write_text(source)
        snapshots.append(path)
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources = resolve(snapshots, ROOT)
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in sources
              if path.is_relative_to(ROOT) and not path.is_relative_to(out)}
    hashes[str(SOURCE)] = digest(ROOT/SOURCE)
    testbench = out/'tb.sv'
    testbench.write_text(bench())
    cases = []
    for synthesis in (False, True):
        mode = 'synthesis' if synthesis else 'generic'
        executable = out/(mode+'.vvp')
        options = ['-DSYNTHESIS=1'] if synthesis else []
        command = ['iverilog', '-g2012', '-s', 'tb', *options, '-o', str(executable),
                   *map(str, sources), str(testbench)]
        compile_log, log = out/(mode+'_compile.log'), out/(mode+'.log')
        with compile_log.open('w') as stream:
            subprocess.run(command, cwd=ROOT, check=True, stdout=stream, stderr=subprocess.STDOUT)
        with log.open('w') as stream:
            subprocess.run(['vvp', str(executable)], cwd=ROOT, check=True,
                           stdout=stream, stderr=subprocess.STDOUT, timeout=180)
        assert 'PASS cycles=65536 observations=131072' in log.read_text()
        cases.append({'synthesis': synthesis, 'passed': True, 'cycles': 65536,
                      'observations': 131072, 'log_sha256': digest(log)})
        print(mode+' PASS', flush=True)
    assert hashes == {name: digest(ROOT/name) for name in hashes}
    (out/'summary.json').write_text(json.dumps({'passed': True, 'reference_commit': REFERENCE,
        'source_sha256': hashes, 'test_sha256': digest(Path(__file__)), 'profiles': cases},
        ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
