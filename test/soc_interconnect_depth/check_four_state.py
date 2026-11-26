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
    parser.add_argument('--reference-ref', default='aa0a169c')
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
    joined_old = ','.join('old_' + name for name in outputs)
    joined_new = ','.join('new_' + name for name in outputs)
    tb = out / 'tb.sv'
    tb.write_text(f'''module tb;
  localparam ADDR_WIDTH=32, DATA_WIDTH=64;
  logic clk=0, rst_n=0;
{chr(10).join(declarations)}
{chr(10).join(instances)}
  localparam INPUT_WIDTH=$bits({{{joined_inputs}}});
  logic [INPUT_WIDTH-1:0] stimulus;
  integer seed=32'h317da462, checks=0;
  always_comb {{{joined_inputs}}}=stimulus;
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
      clk=0;compare();clk=1;compare();clk=0;checks=checks+1;
    end
  endtask
  initial begin
    stimulus='0;cycle();rst_n=1;
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
      cycle();
    end
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
    assert hashes == {name: digest(path) for name, path in originals.items()}
    summary = dict(passed=True, reference_revision=reference, cycles=int(match[1]), public_outputs=outputs,
        synthesis=args.synthesis,
        write_overlap=args.write_overlap,
        source_sha256=hashes, strict_four_state_comparison=True,
        simulator_type_conversion='枚举类型转换为相同位宽逻辑及同值常量；所有表达式和时序块保持',
        simulation_source_sha256={p.name: digest(p) for p in sources},
        testbench_sha256=digest(tb), run_log_sha256=digest(out / 'run.log'), build_command=command)
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(passed=True, cycles=summary['cycles'], public_outputs=len(outputs))))


if __name__ == '__main__':
    main()
