#!/usr/bin/env python3
"""比较任务配置模块的全部公开输出与完整右操作数范围，覆盖四态输入和独立使能。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
REFERENCE_REVISION = '2247144937c2fd04039b9b005151f371d6b51f8f'
sys.path.insert(0, str(ROOT / 'scripts/rtl'))
from source_files import with_dependencies


def prepare(work):
    candidate_path = ROOT / 'rtl/npu/top/npu_task_configuration.sv'
    reference_path = work / 'reference.sv'
    current = candidate_path.read_text()
    original = subprocess.check_output(
        ['git', 'show', f'{REFERENCE_REVISION}:rtl/npu/top/npu_task_configuration.sv'],
        cwd=ROOT, text=True)
    reference_path.write_text(original)
    pattern = r'module npu_task_configuration\s*#\((.*?)\)\s*\((.*?)\n\);'
    params, header = re.search(pattern, current, re.S).groups()
    old_params, old_header = re.search(pattern, original, re.S).groups()
    assert re.sub(r'\s+', '', header) == re.sub(r'\s+', '', old_header)
    assert params == old_params
    ports = []
    for match in re.finditer(r'\b(input|output)\s+(?:wire\s+)?((?:logic|\w+::\w+)(?:\s+signed)?(?:\s*\[[^\]]+\])*)\s+(\w+)\s*((?:\[[^\]]+\]\s*)*)(?:,|$)', header.strip(), re.S):
        ports.append(match.groups())
    assert len(ports) == len(re.findall(r'\b(?:input|output)\b', header))
    out = work / 'four_state'
    out.mkdir(exist_ok=True)
    reference = out / 'reference.sv'
    reference.write_text(re.sub(r'\bmodule\s+npu_task_configuration\b', 'module npu_task_configuration_reference', original, count=1))
    output_count = sum(port[0] == 'output' for port in ports)
    body = ['`timescale 1ns/1ps\nmodule task_configuration_compare #(\n', params, ') ();\n',
            '  integer seed = 32\'h165a84c2;\n  integer cycle;\n  integer bit_index;\n',
            '  integer phase_count = 0;\n  integer output_checks = 0;\n',
            '  logic [31:0] partial_ll, partial_lh, partial_hl, partial_hh;\n']
    for direction, dtype, name, dimensions in ports:
        if direction == 'input':
            body.append(f'  {dtype} {name} {dimensions};\n')
        else:
            body.append(f'  wire {dtype} original_{name} {dimensions};\n')
            body.append(f'  wire {dtype} current_{name} {dimensions};\n')
    param_names = re.findall(r'(?<!local)parameter\s+(?:int\s+unsigned|bit)\s+(\w+)', params)
    connection_params = ', '.join(f'.{name}({name})' for name in param_names)
    for name, module, prefix in [('original_dut', 'npu_task_configuration_reference', 'original_'),
                                 ('current_dut', 'npu_task_configuration', 'current_')]:
        body.append(f'  {module} #({connection_params}) {name} (\n')
        body.append(',\n'.join(f'    .{port_name}({prefix + port_name if direction == "output" else port_name})'
                              for direction, _, port_name, _ in ports))
        body.append('\n  );\n')
    body.append('  task automatic random_inputs;\n    begin\n')
    for direction, dtype, name, _ in ports:
        if direction == 'input' and name not in ('clk', 'rst_n'):
            if dtype.strip() == 'logic':
                body.append(f'      {name} = $random(seed);\n')
            else:
                body.append(f'      for (bit_index=0; bit_index<$bits({name}); bit_index=bit_index+32) {name} = ({name} << 32) | $unsigned($random(seed));\n')
    body.append('''      i_cfg_start_event = (cycle % 19 < 2) || (cycle % 37 == 0);
      i_ctrl_sa_ready = cycle % 7 != 0;
      i_frame_scheduler_ready = cycle % 11 != 0;
      i_vector_start_fire = cycle % 29 == 0;
      if (cycle % 4 == 0) begin
        i_m = cycle % 65;
        i_n = (cycle * 3) % 129;
        i_k = (cycle * 17) % 257;
      end
      if (cycle >= 12000) begin
        case (cycle % 17)
          0: i_n[cycle % 32] = 1'bx;
          1: i_n[cycle % 32] = 1'bz;
          2: i_m[cycle % 32] = 1'bx;
          3: i_m[cycle % 32] = 1'bz;
          4: i_cfg_rhs_tile_packed = 1'bx;
          5: i_cfg_rhs_tile_packed = 1'bz;
          6: i_run_rhs_tile_packed = 1'bx;
          7: i_run_rhs_tile_packed = 1'bz;
          8: i_cfg_start_event = 1'bx;
          9: i_cfg_start_event = 1'bz;
          10: i_ctrl_sa_ready = 1'bx;
          11: i_frame_scheduler_ready = 1'bz;
          default: ;
        endcase
      end
      partial_ll = $random(seed);
      partial_lh = $random(seed);
      partial_hl = $random(seed);
      partial_hh = $random(seed);
      case (cycle % 12)
        0: partial_ll[cycle % 32] = 1'bx;
        1: partial_ll[cycle % 32] = 1'bz;
        2: partial_lh[cycle % 32] = 1'bx;
        3: partial_lh[cycle % 32] = 1'bz;
        4: partial_hl[cycle % 32] = 1'bx;
        5: partial_hl[cycle % 32] = 1'bz;
        6: partial_hh[cycle % 32] = 1'bx;
        7: partial_hh[cycle % 32] = 1'bz;
        8: begin partial_lh = '1; partial_hl = '1; partial_hh = '1; end
        9: begin partial_ll = '0; partial_lh = '0; partial_hl = '0; end
        default: ;
      endcase
    end
  endtask
  task automatic check_outputs;
    begin
''')
    for direction, _, name, dimensions in ports:
        if direction != 'output':
            continue
        suffix = ''
        for i, dimension in enumerate(re.findall(r'\[([^\]]+)\]', dimensions)):
            if ':' in dimension:
                lo, hi = dimension.split(':')
                limit = f'({hi})+1'
            else:
                lo, limit = '0', dimension
            body.append(f'      for (integer index{i}={lo}; index{i}<{limit}; index{i}=index{i}+1)\n')
            suffix += f'[index{i}]'
        body.append(f'      if (original_{name}{suffix} !== current_{name}{suffix}) '
                    f'$fatal(1, "Output {name} differs at cycle %0d", cycle);\n')
    body.append('''      if (original_dut.rhs_allocation_bytes !== current_dut.rhs_allocation_bytes)
        $fatal(1, "RHS extent differs at cycle %0d: reference=%h candidate=%h", cycle,
               original_dut.rhs_allocation_bytes, current_dut.rhs_allocation_bytes);
      output_checks = output_checks + 1;
    end
  endtask
  initial begin
    clk = 0;
    rst_n = 0;
    for (cycle=0; cycle<40000; cycle=cycle+1) begin
      #1;
      random_inputs();
      rst_n = cycle % 397 != 0;
      if (cycle == 24000) begin
        force original_dut.rhs_product_ll = partial_ll;
        force original_dut.rhs_product_lh = partial_lh;
        force original_dut.rhs_product_hl = partial_hl;
        force original_dut.rhs_product_hh = partial_hh;
        force current_dut.rhs_product_ll = partial_ll;
        force current_dut.rhs_product_lh = partial_lh;
        force current_dut.rhs_product_hl = partial_hl;
        force current_dut.rhs_product_hh = partial_hh;
      end
      #2;
      check_outputs();
      clk = 1;
      #2;
      check_outputs();
      if (current_o_cfg_valid_q[2] && current_dut.cfg_capacity_phase == 1) phase_count = phase_count + 1;
      clk = 0;
    end
    if (phase_count < 500) $fatal(1, "Too few completed RHS configurations: %0d", phase_count);
''')
    body.append(f'    $display("TASK_CONFIGURATION_EQUIVALENCE_PASS cycles=%0d checks=%0d output_ports={output_count} rhs_phases=%0d", cycle, output_checks, phase_count);\n    $finish;\n  end\nendmodule\n')
    bench = out / 'compare.sv'
    bench.write_text(''.join(body))
    dependencies = [Path(p) for p in with_dependencies([str(candidate_path)], ROOT) if Path(p) != candidate_path]
    return candidate_path, reference, bench, dependencies, out, output_count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    work = args.out.resolve()
    work.mkdir(parents=True, exist_ok=True)
    candidate, reference, bench, dependencies, out, output_count = prepare(work)
    profiles = [('production', []), ('tile8', ['-Ptask_configuration_compare.p_size=8', '-Ptask_configuration_compare.p_size_shift=3'])]
    summary = {'reference_revision': REFERENCE_REVISION,
               'candidate_sha256': hashlib.sha256(candidate.read_bytes()).hexdigest(),
               'reference_sha256': hashlib.sha256((work / 'reference.sv').read_bytes()).hexdigest(),
               'cycles_per_profile': 40000, 'output_ports': output_count, 'profiles': []}
    for name, options in profiles:
        image = out / (name+'.vvp')
        command = ['iverilog', '-g2012', '-s', 'task_configuration_compare',
                   '-DSYNTHESIS=1', '-DXILINX_FPGA=1', '-DGEMMORA_PS_POOL_BYTES=49152',
                   '-DGEMMORA_PS_FORCE_RAW=1', '-DGEMPACT_PS_COMPRESS=1', *options,
                   '-o', str(image), *map(str, dependencies), str(candidate), str(reference), str(bench)]
        build = subprocess.run(command, capture_output=True, text=True)
        (out / (name+'_compile.log')).write_text(build.stdout+build.stderr)
        if build.returncode:
            raise RuntimeError(build.stderr[-5000:])
        process = subprocess.run(['vvp', str(image)], capture_output=True, text=True, timeout=180)
        (out / (name+'.log')).write_text(process.stdout+process.stderr)
        print(name, process.returncode, process.stdout, flush=True)
        if process.returncode or 'TASK_CONFIGURATION_EQUIVALENCE_PASS' not in process.stdout:
            raise RuntimeError(process.stdout+process.stderr)
        summary['profiles'].append({'name': name, 'pass': True, 'result': process.stdout.strip()})
    (work / 'summary.json').write_text(json.dumps(summary, indent=2)+'\n')


if __name__ == '__main__':
    main()
