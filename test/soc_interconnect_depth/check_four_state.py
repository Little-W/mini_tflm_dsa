#!/usr/bin/env python3
"""比较互连完整公开接口的四态结果，覆盖复位及任意有效与就绪组合。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_current_source as read_rtl_text
from rtl_reference import read_rtl_source_group
from four_state_inputs import packed_width, coverage_declarations, coverage_tasks, parse_coverage

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/soc/soc_axi_interconnect.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def simulation_source(text, name):
    # Icarus 的条件表达式不能隐式赋给枚举类型，保留相同位宽及全部枚举常量。
    def unpack(match):
        width, fields, typename = match.groups()
        values = []
        for entry in fields.split(','):
            values.append(f'    localparam {typename} {entry.strip()};')
        return 'typedef logic' + (width or '') + ' ' + typename + ';\n' + '\n'.join(values)
    text = re.sub(r'typedef\s+enum\s+logic(\s*\[[^\]]+\])?\s*\{([^}]+)\}\s*(\w+)\s*;',
                  unpack, text)
    for module in re.findall(r'\bmodule\s+(\w+)\b', text):
        renamed = name if module == 'soc_axi_interconnect' else name + '_' + module
        text = re.sub(r'\b' + re.escape(module) + r'\b', renamed, text)
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path)
    parser.add_argument('--reference-ref', default='91035729bef91966cd41aba1ad0814705b9ee91b')
    parser.add_argument('--write-overlap', type=int, choices=(0, 1), default=1)
    parser.add_argument('--synthesis', action='store_true')
    parser.add_argument('--predecoded', action='store_true')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if args.reference_root:
        reference_path = args.reference_root.resolve() / SOURCE
        reference = str(args.reference_root.resolve())
    else:
        reference = subprocess.check_output(['git', 'rev-parse', args.reference_ref],
                                            cwd=ROOT, text=True).strip()
        reference_path = out / 'reference_input.sv'
        reference_path.write_bytes(read_rtl_source_group(f'{reference}:{SOURCE}', cwd=ROOT))
    originals = {'reference': reference_path,
                 'current': args.source_root.resolve() / SOURCE}
    hashes = {name: digest(path) for name, path in originals.items()}
    sources = []
    for label, source in originals.items():
        target = out / (label + '.sv')
        source_text = read_rtl_text(source)
        if label == 'current' and args.predecoded:
            import runpy
            bind = runpy.run_path(str(ROOT / 'test/soc_write_ready/run.py'))['bind_predecoded_snapshot']
            source_text = bind(source_text)
        target.write_text(simulation_source(source_text, label))
        sources.append(target)
    header = read_rtl_text(originals['reference']).split('\n);', 1)[0]
    header = re.sub(r'/\*[\s\S]*?\*/|//[^\n]*', '', header)
    ports = re.findall(r'^\s*(input|output)\s+(?:(?:wire|logic)\s+)*(\[[^\]]+\]\s*)?(\w+)\s*[,\n]',
                       header + '\n', re.M)
    assert len(ports) > 130 and len({p[2] for p in ports}) == len(ports)
    inputs = [name for direction, _, name in ports if direction == 'input' and name not in ('clk', 'rst_n')]
    outputs = [name for direction, _, name in ports if direction == 'output']
    declarations = []
    for direction, width, name in ports:
        if name in ('clk', 'rst_n'):
            continue
        width = width or ''
        if direction == 'input':
            declarations.append(f'  logic {width}{name};')
        else:
            declarations += [f'  wire {width}old_{name};', f'  wire {width}new_{name};']
    instances = []
    for label, prefix in [('reference', 'old'), ('current', 'new')]:
        metadata_parameter = ',.p_cpu_aw_predecoded(1)' if label == 'current' and args.predecoded else ''
        connections = ',\n'.join(f'    .{name}({name if direction == "input" else prefix + "_" + name})'
                                  for direction, _, name in ports)
        instances.append(f'''  {label} #(.ADDR_WIDTH(ADDR_WIDTH),.DATA_WIDTH(DATA_WIDTH),.CPU_MEM_DP(65536),
    .READ_OUTSTANDING(4),.WRITE_OUTSTANDING(4),.p_cpu_ram_write_overlap({args.write_overlap}){metadata_parameter}) u_{prefix}(
{connections});''')
    joined_inputs = ','.join(inputs)
    input_width = ' + '.join(packed_width(width) for direction, width, name in ports
                             if direction == 'input' and name not in ('clk', 'rst_n'))
    joined_old = ','.join('old_' + name for name in outputs)
    joined_new = ','.join('new_' + name for name in outputs)
    tb = out / 'tb.sv'
    tb.write_text(f'''module tb;
  localparam ADDR_WIDTH=32, DATA_WIDTH=64;
  logic clk=0, rst_n=0;
{chr(10).join(declarations)}
{chr(10).join(instances)}
  localparam INPUT_WIDTH={input_width};
  logic [INPUT_WIDTH-1:0] stimulus;
  integer seed=32'h317da462, checks=0;
  integer cpu_read=0,npu_read=0,cpu_write=0,npu_write=0;
  integer ram_read=0,ram_write=0,ram_data=0,read_response=0,write_response=0,stalls=0;
  bit count_events=0;
  {coverage_declarations('INPUT_WIDTH')}
  {coverage_tasks('INPUT_WIDTH', '{'+joined_inputs+'}')}
  task compare;
    begin
      #1;
      if ({{{joined_old}}} !== {{{joined_new}}})
        $fatal(1,"Interconnect output mismatch check=%0d stimulus=%h",checks,stimulus);
      if ({{u_old.ram_rd_active_q,u_old.ram_rd_owner_q,u_old.ram_rd_outs_q,
            u_old.cpu_rd_active_q,u_old.cpu_rd_dest_q}} !==
          {{u_new.ram_rd_active_q,u_new.ram_rd_owner_q,u_new.ram_rd_outs_q,
            u_new.cpu_rd_active_q,u_new.cpu_rd_dest_q}})
        $fatal(1,"Interconnect read state mismatch check=%0d",checks);
    end
  endtask
  task cycle;
    begin
      clk=0;observe_inputs();compare();
      if(count_events && rst_n===1'b1)begin
        if(s0_axi_arvalid===1'b1 && new_s0_axi_arready===1'b1)cpu_read++;
        if(s1_axi_arvalid===1'b1 && new_s1_axi_arready===1'b1)npu_read++;
        if(s0_axi_awvalid===1'b1 && new_s0_axi_awready===1'b1)cpu_write++;
        if(s1_axi_awvalid===1'b1 && new_s1_axi_awready===1'b1)npu_write++;
        if(new_m_ram_arvalid===1'b1 && m_ram_arready===1'b1)ram_read++;
        if(new_m_ram_awvalid===1'b1 && m_ram_awready===1'b1)ram_write++;
        if(new_m_ram_wvalid===1'b1 && m_ram_wready===1'b1)ram_data++;
        if(m_ram_rvalid===1'b1 && new_m_ram_rready===1'b1)read_response++;
        if(m_ram_bvalid===1'b1 && new_m_ram_bready===1'b1)write_response++;
        if((new_m_ram_arvalid===1'b1 && m_ram_arready===1'b0) ||
           (new_m_ram_awvalid===1'b1 && m_ram_awready===1'b0) ||
           (new_m_ram_wvalid===1'b1 && m_ram_wready===1'b0))stalls++;
      end
      clk=1;compare();clk=0;checks=checks+1;
    end
  endtask
  task automatic read_once(input bit client);
    bit address_seen,done,accepted,ram_accepted;
    begin
      {{{joined_inputs}}}='0;
      s0_axi_arvalid=!client;s1_axi_arvalid=client;
      s0_axi_araddr=32'h40;s1_axi_araddr=32'h100;
      s0_axi_arsize=2;s1_axi_arsize=3;s0_axi_arburst=1;s1_axi_arburst=1;
      s0_axi_rready=1;s1_axi_rready=1;m_ram_rlast=1;
      address_seen=0;done=0;
      for(integer index=0;index<64 && !done;index++)begin
        m_ram_arready=index>=3;m_ram_rvalid=address_seen;
        #1;
        accepted=client?(s1_axi_arvalid&&new_s1_axi_arready):(s0_axi_arvalid&&new_s0_axi_arready);
        ram_accepted=new_m_ram_arvalid&&m_ram_arready;
        done=m_ram_rvalid&&new_m_ram_rready;
        cycle();
        if(accepted)begin s0_axi_arvalid=0;s1_axi_arvalid=0;end
        if(ram_accepted)address_seen=1;
      end
      if(!done)$fatal(1,"Directed RAM read did not complete client=%0d",client);
      m_ram_rvalid=0;cycle();
    end
  endtask
  task automatic write_once(input bit client);
    bit address_seen,data_seen,done,accepted,data_accepted,ram_accepted;
    begin
      {{{joined_inputs}}}='0;
      s0_axi_awvalid=!client;s1_axi_awvalid=client;
      s0_axi_wvalid=!client;s1_axi_wvalid=client;
      s0_axi_awaddr=32'h80;s1_axi_awaddr=32'h180;
      s0_axi_awsize=2;s1_axi_awsize=3;s0_axi_awburst=1;s1_axi_awburst=1;
      s0_axi_wstrb='1;s1_axi_wstrb='1;s0_axi_wlast=1;s1_axi_wlast=1;
      s0_axi_bready=1;s1_axi_bready=1;
      address_seen=0;data_seen=0;done=0;
      for(integer index=0;index<64 && !done;index++)begin
        m_ram_awready=index>=3;m_ram_wready=index>=5;m_ram_bvalid=address_seen&&data_seen;
        #1;
        accepted=client?(s1_axi_awvalid&&new_s1_axi_awready):(s0_axi_awvalid&&new_s0_axi_awready);
        data_accepted=client?(s1_axi_wvalid&&new_s1_axi_wready):(s0_axi_wvalid&&new_s0_axi_wready);
        ram_accepted=new_m_ram_awvalid&&m_ram_awready;
        done=m_ram_bvalid&&new_m_ram_bready;
        cycle();
        if(accepted)begin s0_axi_awvalid=0;s1_axi_awvalid=0;end
        if(data_accepted)begin s0_axi_wvalid=0;s1_axi_wvalid=0;data_seen=1;end
        if(ram_accepted)address_seen=1;
      end
      if(!done)$fatal(1,"Directed RAM write did not complete client=%0d",client);
      m_ram_bvalid=0;cycle();
    end
  endtask
  initial begin
    initialize_input_coverage();
    {{{joined_inputs}}}='0;cycle();rst_n=1;
    count_events=1;read_once(0);read_once(1);write_once(0);write_once(1);count_events=0;
    if(cpu_read!=1 || npu_read!=1 || cpu_write!=1 || npu_write!=1 ||
       ram_read!=2 || ram_write!=2 || ram_data!=2 || read_response!=2 || write_response!=2 || stalls==0)
      $fatal(1,"Directed interconnect event coverage incomplete");
    for(integer selected=0;selected<INPUT_WIDTH;selected++)begin
      rst_n=0;{{{joined_inputs}}}='0;cycle();rst_n=1;
      for(integer state_index=0;state_index<4;state_index++)begin
        stimulus='0;
        case(state_index)
          0:stimulus[selected]=0;1:stimulus[selected]=1;
          2:stimulus[selected]=1'bx;3:stimulus[selected]=1'bz;
        endcase
        {{{joined_inputs}}}=stimulus;cycle();
      end
    end
    for(integer sample=0;sample<20000;sample++)begin
      rst_n=(sample%257)!=0;
      for(integer bit_i=0;bit_i<INPUT_WIDTH;bit_i++)begin
        case($random(seed)&31)
          0:stimulus[bit_i]=1'bx;
          1:stimulus[bit_i]=1'bz;
          default:stimulus[bit_i]=$random(seed);
        endcase
      end
      if(sample%16==0)stimulus='0;
      if(sample%16==1)stimulus='1;
      {{{joined_inputs}}}=stimulus;
      cycle();
    end
    check_input_coverage();
    $display("INTERCONNECT_EVENTS cpu_read=%0d npu_read=%0d cpu_write=%0d npu_write=%0d ram_read=%0d ram_write=%0d ram_data=%0d read_response=%0d write_response=%0d stalls=%0d",
      cpu_read,npu_read,cpu_write,npu_write,ram_read,ram_write,ram_data,read_response,write_response,stalls);
    $display("INTERCONNECT_FOUR_STATE_PASS cycles=%0d outputs={len(outputs)}",checks);
    $finish;
  end
endmodule
''')
    executable = out / 'simulation.vvp'
    command = ['iverilog', '-g2012', '-s', 'tb', '-o', str(executable), *map(str, sources), str(tb)]
    if args.synthesis:
        command[1:1] = ['-D', 'SYNTHESIS=1']
    with (out / 'build.log').open('w') as stream:
        subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
    result = subprocess.run(['vvp', str(executable)], text=True, capture_output=True, timeout=120)
    (out / 'run.log').write_text(result.stdout + result.stderr)
    match = re.search(r'INTERCONNECT_FOUR_STATE_PASS cycles=(\d+)', result.stdout)
    assert result.returncode == 0 and match, result.stdout + result.stderr
    events=re.search(r'INTERCONNECT_EVENTS cpu_read=(\d+) npu_read=(\d+) cpu_write=(\d+) npu_write=(\d+) '
        r'ram_read=(\d+) ram_write=(\d+) ram_data=(\d+) read_response=(\d+) write_response=(\d+) stalls=(\d+)',result.stdout)
    if not events:
        raise RuntimeError('互连事务事件统计缺失')
    assert hashes == {name: digest(path) for name, path in originals.items()}
    summary = dict(passed=True, reference_revision=reference, cycles=int(match[1]), public_outputs=outputs,
        synthesis=args.synthesis,
        write_overlap=args.write_overlap,
        input_coverage=parse_coverage(result.stdout),
        directed_events=dict(zip(('cpu_read','npu_read','cpu_write','npu_write','ram_read','ram_write',
                                  'ram_data','read_response','write_response','stalled_cycles'),map(int,events.groups()))),
        coverage_helper_sha256=digest(ROOT/'test/four_state_inputs.py'),
        source_sha256=hashes, strict_four_state_comparison=True,
        simulator_type_conversion='枚举类型转换为相同位宽逻辑及同值常量；所有表达式和时序块保持',
        simulation_source_sha256={p.name: digest(p) for p in sources},
        testbench_sha256=digest(tb), run_log_sha256=digest(out / 'run.log'), build_command=command)
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(passed=True, cycles=summary['cycles'], public_outputs=len(outputs))))


if __name__ == '__main__':
    main()
