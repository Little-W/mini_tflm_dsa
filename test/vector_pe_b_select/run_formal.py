#!/usr/bin/env python3
"""证明实际向量 PE 的有效状态与全部操作结果逐周期等价。"""
import argparse
import copy
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


def sections(source):
    first = source.index('  assign pe_operand_en =')
    last = source.index('  // Channel banks provide', first)
    operands = source[first:last]
    outside = source[:first] + source[last:]
    first = outside.rfind('  for (genvar', 0, outside.index('begin : g_pe'))
    last = outside.index('  localparam int ADD_INDEX_WIDTH', first)
    arithmetic = outside[first:last]
    outside = outside[:first] + outside[last:]
    outside = re.sub(r'/\*.*?\*/|//[^\n]*', '', outside, flags=re.S)
    outside = re.sub(r'\s+', '', outside)
    return operands, arithmetic, outside


def wrapper(source, tile, pes, candidate):
    operands, arithmetic, _ = sections(source)
    state_type = re.search(r'typedef enum logic \[5:0\].*?state_t;', source, re.S)[0]
    b_image = "raw_valid[lane] ? raw_b[lane*30+:30] : 30'd0" if candidate else 'raw_b[lane*30+:30]'
    zero_image = "raw_valid[lane] ? 48'd0 : {raw_acc[lane*32+:32], raw_selected_a[lane*16+:16]}" if candidate else "48'd0"
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
      output logic [PE_COUNT*18-1:0] state_a, raw_a,
      output logic [PE_COUNT*30-1:0] state_b, raw_b,
      output logic [PE_COUNT*16-1:0] state_selected_a, raw_selected_a,
      output logic [PE_COUNT*32-1:0] state_acc, raw_acc,
      output logic [PE_COUNT-1:0] raw_valid,
      output logic [PE_COUNT*48-1:0] state_zero_inputs,
      output logic [2:0] state_op
    );
      import vector_engine_pkg::*;
      {state_type}
      logic pe_operand_en;
      logic signed [15:0] pe_a [PE_COUNT], pe_b [PE_COUNT];
      logic signed [31:0] pe_acc [PE_COUNT];
      logic [2:0] pe_op_q;
      {operands}
      {arithmetic}
      assign state_op = pe_op_q;
      for (genvar lane=0; lane<PE_COUNT; lane++) begin : g_observe
        logic captured_valid_q = 1'b1;
        always_ff @(posedge clk) begin
          if (pe_operand_en) captured_valid_q <= g_operand_select[lane].enabled;
        end
        assign raw_valid[lane] = captured_valid_q;
        assign raw_a[lane*18+:18] = g_pe[lane].u_pe.g_dsp.u_dsp.Br2;
        assign raw_b[lane*30+:30] = g_pe[lane].u_pe.g_dsp.u_dsp.Ar2;
        assign raw_selected_a[lane*16+:16] = g_pe[lane].u_pe.operand_a_q;
        assign raw_acc[lane*32+:32] = g_pe[lane].u_pe.operand_acc_q;
        assign state_a[lane*18+:18] = raw_a[lane*18+:18];
        assign state_b[lane*30+:30] = {b_image};
        assign state_selected_a[lane*16+:16] = raw_selected_a[lane*16+:16];
        assign state_acc[lane*32+:32] = raw_acc[lane*32+:32];
        assign state_zero_inputs[lane*48+:48] = {zero_image};
      end
    endmodule
    '''


def hide_internal(module, label):
    module = copy.deepcopy(module)
    module['netnames'] = {
        name if name in module['ports'] else '$' + label + '$' + name:
        dict(net, hide_name=0 if name in module['ports'] else 1)
        for name, net in module['netnames'].items()
    }
    module['cells'] = {'$' + label + '$' + name: cell for name, cell in module['cells'].items()}
    for net in module['netnames'].values():
        net.get('attributes', {}).pop('keep', None)
    return module


def state_view(original, label):
    module = copy.deepcopy(original)
    module['ports'] = {name: port for name, port in module['ports'].items()
                       if name != 'pe_result' and not name.startswith('raw_')}
    return hide_internal(module, label)


def arithmetic_view(original, label, operation, valid, pes):
    module = copy.deepcopy(original)
    first = max(bit for cell in module['cells'].values() for bits in cell['connections'].values()
                for bit in bits if isinstance(bit, int)) + 1
    captured_a = list(range(first, first + 16 * pes))
    captured_b = list(range(first + 16 * pes, first + 32 * pes))
    captured_acc = list(range(first + 32 * pes, first + 64 * pes))
    mapping = {}

    def map_bits(actual, expected):
        assert len(actual) == len(expected)
        for old, new in zip(actual, expected):
            if isinstance(old, int):
                assert old not in mapping or mapping[old] == new
                mapping[old] = new
            else:
                assert old == new

    for lane in range(pes):
        a = captured_a[lane * 16:(lane + 1) * 16]
        b = captured_b[lane * 16:(lane + 1) * 16]
        acc = captured_acc[lane * 32:(lane + 1) * 32]
        if not valid:
            a, acc = ['0'] * 16, ['0'] * 32
            if label == 'reference':
                b = ['0'] * 16
        for name, value, width in [('raw_a', a + [a[15]] * 2, 18),
                                   ('raw_b', b + [b[15]] * 14, 30),
                                   ('raw_selected_a', a, 16), ('raw_acc', acc, 32)]:
            map_bits(module['ports'][name]['bits'][lane * width:(lane + 1) * width], value)
        map_bits([module['ports']['raw_valid']['bits'][lane]], [str(valid)])
    map_bits(module['ports']['state_op']['bits'], [str((operation >> bit) & 1) for bit in range(3)])
    removed = set()
    for name, cell in list(module['cells'].items()):
        if 'dff' not in cell['type'].lower():
            continue
        bits = cell['connections']['Q']
        assert all(bit in mapping for bit in bits), name
        removed.update(bits)
        del module['cells'][name]
    assert removed == set(mapping)
    module['ports'] = {'pe_result': module['ports']['pe_result']}
    for cell in module['cells'].values():
        for name, bits in cell['connections'].items():
            cell['connections'][name] = [mapping.get(bit, bit) for bit in bits]
    for net in module['netnames'].values():
        net.get('attributes', {}).pop('init', None)
        net.get('attributes', {}).pop('keep', None)
        net['bits'] = [mapping.get(bit, bit) for bit in net['bits']]
    for port in module['ports'].values():
        port['bits'] = [mapping.get(bit, bit) for bit in port['bits']]
    for name, bits in [('captured_a', captured_a), ('captured_b', captured_b),
                       ('captured_acc', captured_acc)]:
        module['ports'][name] = {'direction': 'input', 'bits': bits}
        module['netnames'][name] = {'hide_name': 0, 'bits': bits, 'attributes': {}}
    return hide_internal(module, label)


def run_script(folder, stem, commands):
    script = folder / (stem + '.ys')
    script.write_text('\n'.join(commands) + '\n')
    log_path = folder / (stem + '.log')
    with log_path.open('w') as log:
        result = subprocess.run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py',
                                 '--worker', script], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    return result.returncode, log_path.read_text(), hashlib.sha256(log_path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='fa46e6b0')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    engine = ROOT / 'rtl/npu/conv/vector_engine.sv'
    current = engine.read_text()
    reference = read_rtl_source(args.reference_rev + ':' + str(engine.relative_to(ROOT)), cwd=ROOT, text=True)
    assert sections(current)[2] == sections(reference)[2]
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    model = re.search(r'^module DSP48E1\b.*?^endmodule', library.read_text(), re.M | re.S)[0]
    model = re.sub(r'\bspecify\b.*?\bendspecify\b', '', model, flags=re.S)
    model_path = out / 'DSP48E1.sv'
    model_path.write_text(model + '\n')
    dependencies = [ROOT / 'rtl/npu/conv/conv_im2col_pkg.sv', ROOT / 'rtl/npu/conv/vector_engine_pkg.sv',
                    ROOT / 'rtl/npu/conv/vector_pe.sv', model_path]
    report = {'reference_rev': args.reference_rev,
              'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(),
              'source_sha256': hashlib.sha256(current.encode()).hexdigest(),
              'pe_sha256': hashlib.sha256(dependencies[2].read_bytes()).hexdigest(),
              'primitive_library_sha256': hashlib.sha256(library.read_bytes()).hexdigest(),
              'input_constraints': None, 'unchanged_outside_pe_selection_and_connection': True,
              'method': 'Prove captured a/acc and opcode, the effective b image, and zero a/acc in inactive lanes; then prove actual DSP consumers for both validity values and all operation encodings.',
              'validity_observer': 'Formal-only state initialized to true, then updated from the actual lane enable at each actual PE capture; production RTL has no added validity state.',
              'runs': []}
    for tile, pes in [(1, 1), (3, 2), (16, 8), (32, 16)]:
        folder = out / f'tile{tile}_pe{pes}'
        folder.mkdir(exist_ok=True)
        modules = {}
        for label, source in [('reference', reference), ('candidate', current)]:
            path = folder / (label + '.sv')
            path.write_text(wrapper(source, tile, pes, label == 'candidate'))
            output = folder / (label + '.json')
            commands = ['read_slang --top engine_pe_state -D SYNTHESIS=1 -D YOSYS=1 -D VERIFIC=1 ' +
                        ' '.join(shlex.quote(str(p)) for p in dependencies + [path]),
                        'prep -top engine_pe_state -flatten', 'memory_map', 'opt -full',
                        'wreduce', 'opt -full', 'write_json ' + str(output)]
            code, log, _ = run_script(folder, label + '_elaborate', commands)
            if code:
                raise RuntimeError(log[-8000:])
            modules[label] = json.loads(output.read_text())['modules']['engine_pe_state']
        stages = [('state', None, None)]
        if (tile, pes) == (16, 8):
            stages += [(f'operation_{operation}_valid_{valid}', operation, valid)
                       for valid in (0, 1) for operation in range(8)]
        for stem, operation, valid in stages:
            commands = []
            for label in ('reference', 'candidate'):
                selected = (state_view(modules[label], label) if operation is None else
                            arithmetic_view(modules[label], label, operation, valid, pes))
                selected['attributes']['top'] = '1'
                path = folder / (stem + '_' + label + '.json')
                path.write_text(json.dumps({'modules': {label: selected}}))
                commands += ['read_json ' + str(path), 'opt -full', 'wreduce', 'opt -full',
                             'design -stash ' + label]
            commands += ['design -copy-from reference -as reference reference',
                         'design -copy-from candidate -as candidate candidate']
            if operation is None:
                commands += ['equiv_make reference candidate comparison', 'hierarchy -top comparison',
                             'equiv_simple', 'equiv_induct -seq 2', 'equiv_status -assert']
            else:
                commands += ['miter -equiv -flatten reference candidate comparison',
                             'hierarchy -top comparison', 'opt -full', 'wreduce', 'opt -full',
                             'sat -verify -prove trigger 0 -show-inputs -show-outputs']
            code, log, log_hash = run_script(folder, stem, commands)
            success = 'Equivalence successfully proven!' if operation is None else 'SUCCESS!'
            record = {'tile': tile, 'pe_count': pes, 'stage': stem,
                      'passed': code == 0 and success in log, 'log_sha256': log_hash}
            report['runs'].append(record)
            print(json.dumps(record), flush=True)
            if not record['passed']:
                raise RuntimeError(log[-10000:])
    assert current == engine.read_text()
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
