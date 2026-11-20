#!/usr/bin/env python3
"""从完整前端提取行释放计算，证明自由输入等价并测量分组前缀结构。"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import resource
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/conv/conv_im2col_frontend.sv'
sys.path.insert(0, str(ROOT / 'test'))
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from rtl_reference import read_rtl_source
import map_wide_alu as mapper
from netlist_metrics import analyze
from remap_fpga_luts import mapping_commands, physical_cost_library

BEGIN = '  // 请求与预取各保留一个退休行号计算端口，两个预取阶段按原有采样周期共用端口。\n'
END = '  // 位置解码使用已接受的描述符，快速请求的资格条件保证输入位置与保存位置相同。\n'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def retirement_unit(name, body, observe_internal=False):
    width = 202 if observe_internal else 64
    observations = ['retirement_result']
    if observe_internal:
        for port in range(2):
            observations += [f'g_retirement_port[{port}].{signal}' for signal in
                ('padded_row', 'shifted_row', 'incremented_row', 'bounded_row',
                 'unused_increment_carry')]
    return f'''module {name}(input logic [163:0] i_value,
    output logic [{width-1}:0] o_value);
  logic [15:0] request_y_q, pad_top, retire_last_row_q;
  logic [34:0] iy, pfa_y, pf0_y;
  logic request_pending, retire_enabled_q, short_pixel_q;
  logic [3:0] retire_shift_q, prefetch_phase;
  typedef struct packed {{logic [15:0] pad_top;}} config_t;
  config_t c;
  logic [1:0][15:0] retirement_input;
  logic [1:0][31:0] retirement_result;
  logic [31:0] request_retire;
  assign {{request_y_q, pad_top, retire_last_row_q, iy, pfa_y, pf0_y,
      request_pending, retire_enabled_q, short_pixel_q, retire_shift_q,
      prefetch_phase}} = i_value;
  assign c.pad_top = pad_top;
''' + body + '  assign o_value = {' + ', '.join(observations) + '};\nendmodule\n'


def increment_unit(name, body):
    begin = body.index('    assign shifted_row =')
    begin = body.index('\n', begin) + 1
    end = body.index('    assign bounded_row =', begin)
    calculation = body[begin:end]
    return f'''module {name}(input logic [17:0] i_value,
    output logic [17:0] o_value);
  logic [16:0] shifted_row, incremented_row;
  logic short_pixel_q, unused_increment_carry;
  assign {{shifted_row, short_pixel_q}} = i_value;
''' + calculation + '''
  assign o_value = {unused_increment_carry, incremented_row};
endmodule
'''


def proof_module(name, input_bits, output_bits, undefined=False):
    equality = '===' if undefined else '=='
    return f'''module {name}_proof(input logic [{input_bits-1}:0] i_value,
    output logic o_equal);
  logic [{output_bits-1}:0] reference_value, current_value;
  {name}_reference u_reference(.i_value(i_value), .o_value(reference_value));
  {name}_current u_current(.i_value(i_value), .o_value(current_value));
  assign o_equal = reference_value {equality} current_value;
endmodule
'''


def measured_module(name, input_bits, output_bits):
    return f'''module measured(input logic clk,
    input logic [{input_bits-1}:0] i_value,
    output logic [{output_bits-1}:0] o_value);
  logic [{input_bits-1}:0] input_q;
  logic [{output_bits-1}:0] next_value;
  always_ff @(posedge clk) begin
    input_q <= i_value;
    o_value <= next_value;
  end
  {name} u_calculation(.i_value(input_q), .o_value(next_value));
endmodule
'''


def run(script, log, text):
    script.write_text(text)
    with log.open('w') as stream:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
            '--worker', str(script)], cwd=script.parent, stdout=stream, stderr=subprocess.STDOUT,
            check=True)
    return log.read_text()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--skip-synthesis', action='store_true')
    parser.add_argument('--padded-row-dsp', action='store_true',
                        help='两个补边加法使用组合 DSP，其余算术保留普通进位实现')
    parser.add_argument('--lut-costs', nargs='+', type=float, default=[1.0, 0.75])
    args = parser.parse_args()
    if any(not 0 < cost <= 1 for cost in args.lut_costs):
        parser.error('LUT 面积成本必须大于零且不超过一')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = {'reference': read_rtl_source(args.reference + ':' + SOURCE, cwd=ROOT, text=True),
               'current': (ROOT / SOURCE).read_text()}
    bodies = {label: text[text.index(BEGIN):text.index(END)] for label, text in sources.items()}
    if sources['current'].replace(bodies['current'], bodies['reference'], 1) != sources['reference']:
        raise ValueError('行释放计算以外存在源码变化，需要扩展证明范围')
    report = {'reference_commit': subprocess.check_output(['git', 'rev-parse', args.reference],
        cwd=ROOT, text=True).strip(), 'source_sha256': {label: digest(text.encode())
        for label, text in sources.items()}, 'unchanged_outside_retirement': True,
        'inputs_constrained': False, 'proofs': [], 'synthesis': []}

    def save():
        report['maximum_resident_kib'] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')

    for mode in ('generic', 'fpga'):
        defines = '-D ASIC_SYNTHESIS=1' if mode == 'generic' else \
            '-D SYNTHESIS=1 -D XILINX_FPGA=1 -D YOSYS=1 -D VERIFIC=1'
        for name, bits_in, bits_out in (('increment', 18, 18), ('retirement', 164, 202)):
            folder = out / f'{mode}_{name}'
            folder.mkdir(exist_ok=True)
            rtl = folder / 'proof.sv'
            make_unit = increment_unit if name == 'increment' else \
                lambda unit_name, body: retirement_unit(unit_name, body, True)
            rtl.write_text(''.join(make_unit(name + '_' + label, body)
                for label, body in bodies.items()) + proof_module(name, bits_in, bits_out))
            log = folder / 'proof.log'
            text = run(folder / 'proof.ys', log, f'read_slang --top {name}_proof {defines} ' +
                shlex.quote(str(rtl)) + f'\nprep -top {name}_proof -flatten\n'
                'sat -verify -prove o_equal 1 -show-inputs -show-outputs\n')
            passed = 'SAT proof finished - no model found: SUCCESS!' in text
            report['proofs'].append({'mode': mode, 'name': name, 'input_bits': bits_in,
                'observed_bits': bits_out, 'passed': passed, 'rtl_sha256': digest(rtl.read_bytes()),
                'log_sha256': digest(log.read_bytes())})
            save()
            if not passed:
                raise RuntimeError('组合等价证明未完成')
            print(json.dumps(report['proofs'][-1], ensure_ascii=False), flush=True)

    # 未定义位模型允许任意输入位为未知；case equality 同时检查值和已知状态。
    for name, bits_in, bits_out in (('increment', 18, 18), ('retirement', 164, 202)):
        folder = out / f'undefined_{name}'
        folder.mkdir(exist_ok=True)
        make_unit = increment_unit if name == 'increment' else \
            lambda unit_name, body: retirement_unit(unit_name, body, True)
        rtl = folder / 'proof.sv'
        rtl.write_text(''.join(make_unit(name + '_' + label, body)
            for label, body in bodies.items()) + proof_module(name, bits_in, bits_out, True))
        log = folder / 'proof.log'
        text = run(folder / 'proof.ys', log,
            f'read_slang --top {name}_proof -D SYNTHESIS=1 -D XILINX_FPGA=1 ' +
            shlex.quote(str(rtl)) + f'\nprep -top {name}_proof -flatten\n'
            'sat -enable_undef -verify -prove o_equal 1 -set-any-undef i_value '
            '-show-inputs -show-outputs\n')
        passed = 'SAT proof finished - no model found: SUCCESS!' in text
        report['proofs'].append({'mode': 'fpga_undefined', 'name': name,
            'input_bits': bits_in, 'observed_bits': bits_out, 'passed': passed,
            'constraint': 'At least one input bit is undefined; other input bits are unconstrained',
            'comparison': 'case equality', 'rtl_sha256': digest(rtl.read_bytes()),
            'log_sha256': digest(log.read_bytes())})
        save()
        if not passed:
            raise RuntimeError('未定义输入的组合等价证明未完成')
        print(json.dumps(report['proofs'][-1], ensure_ascii=False), flush=True)

    if not args.skip_synthesis:
        raw = out / 'native_lut_library.lut'
        run(out / 'library.ys', out / 'library.log',
            'read_verilog -lib -specify +/xilinx/cells_sim.v\nadd -mod lut_library_top\n'
            'abc9_ops -prep_lut 0\nabc9_ops -write_lut ' + shlex.quote(str(raw)) + '\n')
        report['mapping'] = {'family': 'xc7', 'max_lut_inputs': 6,
            'wire_delay_ps': 500, 'delay_target_ps': 6667, 'small_lut_area_costs': args.lut_costs,
            'dsp_budget_reallocation': False, 'padded_row_combinational_dsps': 2 if args.padded_row_dsp else 0}
        units = [('retirement', 164, 64)] if args.padded_row_dsp else \
            [('increment', 18, 18), ('retirement', 164, 64)]
        for name, bits_in, bits_out in units:
            for label, body in bodies.items():
                folder = out / f'mapped_{name}_{label}'
                folder.mkdir(exist_ok=True)
                make_unit = increment_unit if name == 'increment' else retirement_unit
                rtl = folder / 'measure.sv'
                rtl.write_text(make_unit(name + '_' + label, body) +
                    measured_module(name + '_' + label, bits_in, bits_out))
                pre_lut = folder / 'pre_lut.il'
                padded_parameters = []
                if args.padded_row_dsp:
                    pre_alu = folder / 'pre_alu.json'
                    run(folder / 'prepare.ys', folder / 'prepare.log',
                        'read_slang --top measured -D SYNTHESIS=1 -D XILINX_FPGA=1 ' +
                        shlex.quote(str(rtl)) + '\n'
                        'synth_xilinx -top measured -family xc7 -noiopad -noclkbuf -flatten '
                        '-run begin:fine\nselect measured\nwrite_json -selected ' +
                        shlex.quote(str(pre_alu)) + '\n')
                    design = json.loads(pre_alu.read_text())
                    module = design['modules']['measured']
                    padded_rows = [net['bits'] for net_name, net in module['netnames'].items()
                                   if net_name.endswith('.padded_row')]
                    if len(padded_rows) != 2:
                        raise RuntimeError('补边加法的两个完整结果没有保留')
                    selected = []
                    for bits in padded_rows:
                        drivers = [cell_name for cell_name, cell in module['cells'].items()
                                   if cell['type'] == '$alu' and cell['connections']['Y'] == bits]
                        if len(drivers) != 1:
                            raise RuntimeError('补边结果没有唯一的算术驱动')
                        selected.append({'cell': drivers[0]})
                        parameters = module['cells'][drivers[0]]['parameters']
                        padded_parameters.append({key: mapper.integer(value)
                                                  for key, value in parameters.items()})
                    mapper.apply_mapping(module, {'selected': selected})
                    mapped_alu = folder / 'mapped_alu.json'
                    mapped_alu.write_text(json.dumps(design, separators=(',', ':')) + '\n')
                    autoidx = mapped_alu.with_suffix('.autoidx.il')
                    autoidx.write_text('autoidx ' + str(mapper.next_autoidx(design)) + '\n')
                    run(folder / 'pre_lut.ys', folder / 'pre_lut.log',
                        'read_rtlil ' + shlex.quote(str(autoidx)) + '\nread_json ' +
                        shlex.quote(str(mapped_alu)) + '\n'
                        'read_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\n'
                        'read_verilog -lib -overwrite +/xilinx/cells_xtra.v\n'
                        'verilog_defaults -push\nverilog_defaults -add -sv\ntechmap -map ' +
                        shlex.quote(str(ROOT / 'scripts/fpga/techmap/wide_alu_dsp.sv')) + '\n'
                        'verilog_defaults -pop\nopt_clean\n'
                        'synth_xilinx -top measured -family xc7 -noiopad -noclkbuf -flatten '
                        '-run fine:map_luts\nwrite_rtlil ' + shlex.quote(str(pre_lut)) + '\n')
                else:
                    run(folder / 'prepare.ys', folder / 'prepare.log',
                        'read_slang --top measured -D SYNTHESIS=1 -D XILINX_FPGA=1 ' +
                        shlex.quote(str(rtl)) + '\n'
                        'synth_xilinx -top measured -family xc7 -noiopad -noclkbuf -flatten '
                        '-run begin:map_luts\nwrite_rtlil ' + shlex.quote(str(pre_lut)) + '\n')
                for cost in args.lut_costs:
                    result = folder / ('cost_' + format(cost, 'g'))
                    result.mkdir(exist_ok=True)
                    library = result / 'physical_lut_cost.lut'
                    physical_cost_library(raw, library, 6, cost)
                    text = run(result / 'map.ys', result / 'map.log', mapping_commands('measured',
                        pre_lut, result, 'physical-cost', 6667, 500, library))
                    if 'Networks are equivalent.' not in text:
                        raise RuntimeError('ABC9 网络等价检查未完成')
                    mapped = result / 'mapped.json'
                    measured = analyze(json.loads(mapped.read_text())['modules']['measured'])
                    if not measured['paths']['graph_complete']:
                        raise RuntimeError('寄存器之间的组合路径包含未分析单元')
                    if args.padded_row_dsp:
                        if measured['resources']['dsp48e1'] != 2 or any(
                                sum(step['type'] == 'DSP48E1' for step in path['path']) > 1
                                for path in measured['paths']['register_to_register_paths']):
                            raise RuntimeError('局部测量的 DSP 数量或组合连接发生变化')
                    (result / 'metrics.json').write_text(json.dumps(measured, ensure_ascii=False, indent=2) + '\n')
                    entry = {'name': name, 'label': label, 'small_lut_area_cost': cost,
                        'resources': measured['resources'], 'padded_row_dsp_parameters': padded_parameters,
                        'longest_register_path_cells': measured['paths']['longest_register_path_cells'],
                        'rtl_sha256': digest(rtl.read_bytes()), 'mapped_sha256': digest(mapped.read_bytes())}
                    report['synthesis'].append(entry)
                    save()
                    print(json.dumps({'name': name, 'label': label, 'small_lut_area_cost': cost,
                        'lut': entry['resources']['logic_lut_cells'],
                        'carry4': entry['resources']['carry4'],
                        'depth': entry['longest_register_path_cells']}, ensure_ascii=False), flush=True)
                    for path in (mapped, result / 'mapped.v'):
                        with gzip.open(str(path) + '.gz', 'wb') as stream:
                            stream.write(path.read_bytes())
                        path.unlink()
                with gzip.open(str(pre_lut) + '.gz', 'wb') as stream:
                    stream.write(pre_lut.read_bytes())
                pre_lut.unlink()
    if sources['current'] != (ROOT / SOURCE).read_text():
        raise RuntimeError('验证期间前端源码发生变化')
    report['passed'] = all(item['passed'] for item in report['proofs'])
    save()


if __name__ == '__main__':
    main()
