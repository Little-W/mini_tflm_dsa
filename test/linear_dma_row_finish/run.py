#!/usr/bin/env python3
"""验证线性 DMA 行末状态、全部公开输出和完整内部状态。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'test'))
from four_state_inputs import packed_width, coverage_declarations, coverage_tasks, parse_coverage
SOURCE = Path('rtl/npu/dma/axi_linear_block_dma.sv')
PROFILES = (
    dict(SIZE=16, BUS_WIDTH=32, READ_OUTSTANDING=4, WRITE_OUTSTANDING=4),
    dict(SIZE=16, BUS_WIDTH=64, READ_OUTSTANDING=4, WRITE_OUTSTANDING=4),
    dict(SIZE=16, BUS_WIDTH=128, READ_OUTSTANDING=1, WRITE_OUTSTANDING=1),
    dict(SIZE=64, BUS_WIDTH=64, CACHE_BLOCKS=64, RD_CONTEXT_DEPTH=3),
    dict(SIZE=2, BUS_WIDTH=32, RD_CONTEXT_DEPTH=1, READ_OUTSTANDING=1, WRITE_OUTSTANDING=1),
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prove(root, reference, current, out, resolver):
    out.mkdir(parents=True, exist_ok=True)
    # 保存拍计数与行末比较之间的关系，归纳检查覆盖新增状态。
    observed = reference.replace('endmodule',
        '    (* keep = 1 *) wire wr_cross_row_end_q = wr_cross_row_end;\nendmodule', 1)
    (out / 'reference.sv').write_text(observed)
    # 组合分解节点在状态前推后具有不同定义；以原寄存器及公开输出比较完整行为。
    for name in ('wr_cross_equal_group', 'wr_cross_row_end', 'wr_plain_row_end',
                 'wr_cfg_cross_last', 'wr_cfg_burst_len_ext', 'wr_tail_beat', 'wr_row_end'):
        current = re.sub(r'\b' + name + r'\b', 'candidate_' + name, current)
    (out / 'current.sv').write_text(current)
    records = []
    for mode, flags in (('generic', ''), ('fpga_synthesis', '-DSYNTHESIS=1 -DXILINX_FPGA=1')):
        for index, parameters in enumerate(PROFILES):
            options = ' '.join(f'-G{key}={value}' for key, value in parameters.items())
            commands = []
            for label in ('reference', 'current'):
                paths = resolver([out / (label + '.sv')], root)
                commands += [
                    f'read_slang {flags} --top axi_linear_block_dma {options} ' +
                    shlex.join(map(str, paths)),
                    'prep -top axi_linear_block_dma -flatten', 'memory_map', 'async2sync',
                    'opt_clean', f'rename axi_linear_block_dma {label}', f'design -stash {label}',
                ]
            commands += [
                'design -copy-from reference -as reference reference',
                'design -copy-from current -as current current',
                'equiv_make reference current comparison', 'hierarchy -top comparison',
                'equiv_simple -short -seq 1', 'opt_clean', 'equiv_induct -seq 3',
                'equiv_status -assert',
            ]
            script, log = out / f'{mode}_{index}.ys', out / f'{mode}_{index}.log'
            script.write_text('\n'.join(commands) + '\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT,
                               check=True, timeout=240)
            text = log.read_text()
            counts = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
            if not counts or int(counts[2]) or 'Equivalence successfully proven' not in text:
                raise RuntimeError('完整状态等价性检查未完成')
            records.append(dict(mode=mode, parameters=parameters, equivalent_bits=int(counts[1]),
                                passed=True, log_sha256=digest(log)))
            print(mode, index, counts[1], 'PASS', flush=True)
    return records


def simulate(root, reference, current, current_path, out, resolver, cycles):
    out.mkdir(parents=True, exist_ok=True)
    for label, text in (('reference', reference), ('current', current)):
        # 展开嵌套 packed 字段的位选择；同位宽中间线保留逐位四态值。
        expression='rd_incoming.response[$bits(response_context_t)-1:RD_TAG_WIDTH]'
        if text.count(expression)!=1:
            raise RuntimeError('读取上下文的字段选择表达式无法唯一定位')
        text=text.replace('assign context_storage_i_wr_data = '+expression+';',
            'wire [$bits(response_context_t)-1:0] simulation_response_data = rd_incoming.response;\n'
            '    assign context_storage_i_wr_data = simulation_response_data[$bits(response_context_t)-1:RD_TAG_WIDTH];')
        (out / (label + '.sv')).write_text(
            text.replace('module axi_linear_block_dma', 'module ' + label, 1))
    header = reference.split('\n);', 1)[0]
    header = re.sub(r'/\*[\s\S]*?\*/|//[^\n]*', '', header)
    ports = re.findall(
        r'^\s*(input|output)\s+(?:(?:wire|logic|reg|signed)\s+)*'
        r'(\[[^\]]+\]\s*)?(\w+)\s*(\[[^\]]+\])?\s*(?:=[^,\n]*)?[,\n]',
        header + '\n', re.M)
    if len(ports) <= 65 or len({port[2] for port in ports}) != len(ports):
        raise RuntimeError('DMA 公开端口解析不完整')
    inputs = [name for direction, width, name, array in ports
              if direction == 'input' and name not in ('clk', 'rst_n')]
    if any(array for direction,_,name,array in ports if name in inputs):
        raise RuntimeError('输入数组需要显式展开后参与四态比较')
    input_width=' + '.join(packed_width(width) for direction,width,name,array in ports if name in inputs)
    outputs = [(name, array) for direction, width, name, array in ports if direction == 'output']
    declarations, instances = [], []
    for direction, width, name, array in ports:
        if name in ('clk', 'rst_n'):
            continue
        for prefix in ([''] if direction == 'input' else ['old_', 'new_']):
            kind = 'logic' if direction == 'input' else 'wire'
            signed = 'signed ' if name == 'wr_data' else ''
            declarations.append(f'    {kind} {signed}{width}{prefix}{name} {array};')
    for label, prefix in (('reference', 'old_'), ('current', 'new_')):
        connections = ', '.join(f'.{name}({name if direction == "input" else prefix + name})'
                                for direction, width, name, array in ports)
        instances.append(f'{label} #(.BUS_WIDTH(BUS_WIDTH),.SIZE(SIZE),.DATA_WIDTH(DATA_WIDTH),'
                         f'.READ_OUTSTANDING(4),.WRITE_OUTSTANDING(4)) u_{label}({connections});')
    checks = '\n'.join(
        (f'for(integer lane=0;lane<BUS_WIDTH/8;lane++) '
         f'if(old_{name}[lane] !== new_{name}[lane]) '
         f'$fatal(1,"array {name} mismatch cycle=%0d",count);') if array else
        (f'if(old_{name} !== new_{name}) $fatal(1,"{name} mismatch cycle=%0d",count);')
        for name, array in outputs)
    bench = '''module tb;
localparam BUS_WIDTH=64,SIZE=16,DATA_WIDTH=16,REG_WIDTH=32,CACHE_BLOCKS=4,RD_TAG_WIDTH=3;
logic clk=0,rst_n=0;
''' + '\n'.join(declarations + instances) + f'''
localparam INPUT_BITS={input_width};
logic [INPUT_BITS-1:0] stimulus;
integer seed=32'h279361ab,count=0;
integer write_commands=0,read_commands=0,write_addresses=0,write_data=0,write_responses=0;
integer read_addresses=0,read_responses=0,write_completions=0,read_completions=0;
integer plain_rows=0,cross_rows=0,aborts=0,stalls=0;
bit count_events=0;
logic previous_write_done=0,previous_read_done=0;
{coverage_declarations('INPUT_BITS')}
{coverage_tasks('INPUT_BITS','{'+','.join(inputs)+'}')}
task compare;
begin
 #1;
 {checks}
 if(u_current.wr_cross_row_end_q !== u_reference.wr_cross_row_end)
  $fatal(1,"row flag mismatch cycle=%0d",count);
end
endtask
task tick;
begin
 clk=0;observe_inputs();compare();
 if(count_events && rst_n===1'b1)begin
  if(wr_start===1'b1 && u_current.wr_active===1'b0 && abort===1'b0)write_commands++;
  if(rd_start===1'b1 && new_rd_start_ready===1'b1)read_commands++;
  if(new_m_axi_awvalid===1'b1 && m_axi_awready===1'b1)write_addresses++;
  if(new_m_axi_wvalid===1'b1 && m_axi_wready===1'b1)begin
   write_data++;
   if(u_current.wr_row_end===1'b1)begin
    if(u_current.wr_row_cross===1'b1)cross_rows++;else plain_rows++;
   end
  end
  if(m_axi_bvalid===1'b1 && new_m_axi_bready===1'b1)write_responses++;
  if(new_m_axi_arvalid===1'b1 && m_axi_arready===1'b1)read_addresses++;
  if(m_axi_rvalid===1'b1 && new_m_axi_rready===1'b1)read_responses++;
  if(new_wr_done===1'b1 && previous_write_done!==1'b1)write_completions++;
  if(new_rd_done===1'b1 && previous_read_done!==1'b1)read_completions++;
  if(abort===1'b1)aborts++;
  if((new_m_axi_awvalid===1'b1 && m_axi_awready===1'b0) ||
     (new_m_axi_wvalid===1'b1 && m_axi_wready===1'b0))stalls++;
 end
 previous_write_done=new_wr_done;previous_read_done=new_rd_done;
 clk=1;compare();clk=0;count++;
end
endtask
task automatic write_transfer(input bit crossing,input bit cancel);
 integer pending;
 bit done,last_data,response;
begin
 {{{','.join(inputs)}}}='0;
 wr_base_addr=crossing?32'h83:32'h80;wr_row_stride=16;
 wr_rows_to_write=2;wr_burst_len_m1=1;src_wmask='1;src_wdata='1;
 wr_start=1;tick();wr_start=0;pending=0;done=0;
 for(integer index=0;index<128 && !done;index++)begin
  m_axi_awready=index%3!=0;m_axi_wready=index%4!=0;src_wvalid=index%5!=0;
  m_axi_bvalid=pending!=0;abort=cancel&&index==4;
  #1;
  last_data=new_m_axi_wvalid&&m_axi_wready&&new_m_axi_wlast;
  response=m_axi_bvalid&&new_m_axi_bready;
  done=new_wr_done;
  tick();
  pending=pending+int'(last_data)-int'(response);
 end
 if(!done || pending!=0)$fatal(1,"Directed DMA write did not complete crossing=%0d cancel=%0d",crossing,cancel);
 {{{','.join(inputs)}}}='0;tick();
end
endtask
task automatic read_transfer;
 bit pending,done,accepted;
begin
 {{{','.join(inputs)}}}='0;
 rd_base_addr=32'h40;rd_row_stride=8;rd_rows_to_read=1;rd_valid_cols=8;rd_burst_len_m1=0;
 rd_start=1;tick();rd_start=0;pending=0;done=0;
 for(integer index=0;index<64 && !done;index++)begin
  m_axi_arready=index>=3;m_axi_rvalid=pending;m_axi_rlast=1;m_axi_rdata='1;
  #1;accepted=new_m_axi_arvalid&&m_axi_arready;
  if(m_axi_rvalid&&new_m_axi_rready)pending=0;
  done=new_rd_done;
  tick();
  if(accepted)pending=1;
 end
 if(!done)$fatal(1,"Directed DMA read did not complete");
 {{{','.join(inputs)}}}='0;tick();
end
endtask
initial begin
 initialize_input_coverage();
 {{{','.join(inputs)}}}='0;tick();rst_n=1;
 count_events=1;read_transfer();write_transfer(0,0);write_transfer(1,0);write_transfer(0,1);count_events=0;
 if(read_commands!=1 || write_commands!=3 || read_completions!=1 || write_completions!=3 ||
    read_addresses==0 || read_responses==0 || write_addresses==0 || write_data==0 ||
    write_responses==0 || plain_rows<2 || cross_rows<2 || aborts!=1 || stalls==0)
  $fatal(1,"Directed DMA event coverage incomplete");
 for(integer selected=0;selected<INPUT_BITS;selected++)begin
  rst_n=0;{{{','.join(inputs)}}}='0;tick();rst_n=1;
  for(integer state_index=0;state_index<4;state_index++)begin
   stimulus='0;
   case(state_index)
    0:stimulus[selected]=0;1:stimulus[selected]=1;
    2:stimulus[selected]=1'bx;3:stimulus[selected]=1'bz;
   endcase
   {{{','.join(inputs)}}}=stimulus;tick();
  end
 end
 for(integer sample=0;sample<{cycles};sample++)begin
  rst_n=sample%127!=0;
  for(integer bit_index=0;bit_index<INPUT_BITS;bit_index++)begin
   case($random(seed)&31)
    0:stimulus[bit_index]=1'bx;
    1:stimulus[bit_index]=1'bz;
    default:stimulus[bit_index]=$random(seed);
   endcase
  end
  if(sample%16==0)stimulus='0;
  if(sample%16==1)stimulus='1;
  if(sample%43==0 && sample!=0)rst_n=1'bx;
  if(sample%47==0 && sample!=0)rst_n=1'bz;
  {{{','.join(inputs)}}}=stimulus;
  tick();
 end
 check_input_coverage();
 $display("DMA_ROW_EVENTS write_commands=%0d read_commands=%0d write_addresses=%0d write_data=%0d write_responses=%0d read_addresses=%0d read_responses=%0d write_completions=%0d read_completions=%0d plain_rows=%0d cross_rows=%0d aborts=%0d stalls=%0d",
  write_commands,read_commands,write_addresses,write_data,write_responses,read_addresses,read_responses,
  write_completions,read_completions,plain_rows,cross_rows,aborts,stalls);
 $display("DMA_ROW_FOUR_STATE_PASS cycles=%0d outputs={len(outputs)}",count);$finish;
end
endmodule
'''
    (out / 'tb.sv').write_text(bench)
    dependencies = resolver([current_path], root)[1:]
    records = []
    for mode, flags in (('generic', []), ('fpga_synthesis', ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'])):
        binary, compile_log = out / (mode + '.vvp'), out / (mode + '_compile.log')
        with compile_log.open('w') as stream:
            subprocess.run(['iverilog', '-g2012', *flags, '-s', 'tb', '-o', str(binary),
                            str(out / 'reference.sv'), str(out / 'current.sv'),
                            *map(str, dependencies), str(out / 'tb.sv')], stdout=stream,
                           stderr=subprocess.STDOUT, check=True, timeout=60)
        result = subprocess.run(['vvp', str(binary)], capture_output=True, text=True, timeout=180)
        log = out / (mode + '.log')
        log.write_text(result.stdout + result.stderr)
        if result.returncode or 'DMA_ROW_FOUR_STATE_PASS' not in result.stdout:
            raise RuntimeError(result.stdout + result.stderr)
        count=re.search(r'DMA_ROW_FOUR_STATE_PASS cycles=(\d+)',result.stdout)
        events=re.search(r'DMA_ROW_EVENTS write_commands=(\d+) read_commands=(\d+) write_addresses=(\d+) '
            r'write_data=(\d+) write_responses=(\d+) read_addresses=(\d+) read_responses=(\d+) '
            r'write_completions=(\d+) read_completions=(\d+) plain_rows=(\d+) cross_rows=(\d+) '
            r'aborts=(\d+) stalls=(\d+)',result.stdout)
        if not count or not events:
            raise RuntimeError('DMA 周期与事务事件统计缺失')
        actual_cycles=int(count[1])
        records.append(dict(mode=mode, cycles=actual_cycles, public_outputs=len(outputs),
                            comparisons=2*actual_cycles*(sum(8 if array else 1 for _,array in outputs)+1),
                            input_coverage=parse_coverage(result.stdout),
                            directed_events=dict(zip(('write_commands','read_commands','write_addresses','write_data',
                                'write_responses','read_addresses','read_responses','write_completions','read_completions',
                                'plain_rows','cross_rows','aborts','stalled_cycles'),map(int,events.groups()))),
                            unknown_controls=True, unknown_payload=True, unknown_reset=True,
                            packed_member_selection='嵌套 packed 字段先赋给同位宽 wire，再执行原范围位选择',
                            simulation_source_sha256={label:digest(out/(label+'.sv')) for label in ('reference','current')},
                            testbench_sha256=digest(out/'tb.sv'),
                            passed=True, log_sha256=digest(log)))
        print(mode, result.stdout.strip(), flush=True)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference', default='73b91678')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cycles', type=int, default=30000)
    parser.add_argument('--section',choices=('all','formal','four_state'),default='all')
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current_path = root / SOURCE
    current = current_path.read_text()
    reference = subprocess.check_output(['git', 'show', f'{args.reference}:{SOURCE}'],
                                        cwd=ROOT, text=True)
    resolver = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']
    paths = [*resolver([current_path], root), Path(__file__).resolve(),ROOT/'test/four_state_inputs.py']
    hashes = {str(path): digest(path) for path in paths}
    report = dict(reference=args.reference, source_sha256=hashes,
                  reference_sha256=hashlib.sha256(reference.encode()).hexdigest(),
                  functional_inputs_constrained=False, all_public_outputs_compared=True,
                  all_matching_state_compared=args.section!='four_state', row_flag_relation_proved=args.section!='four_state')
    if args.section in ('all','formal'):
        report['formal'] = prove(root, reference, current, out / 'formal', resolver)
    if args.section in ('all','four_state'):
        report['four_state'] = simulate(root, reference, current, current_path, out / 'four_state',
                                        resolver, args.cycles)
    if hashes != {str(path): digest(path) for path in paths}:
        raise RuntimeError('验证期间源码发生变化')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
