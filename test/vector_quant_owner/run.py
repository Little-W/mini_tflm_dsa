#!/usr/bin/env python3
"""证明向量运算状态范围以及量化控制的唯一所有者。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
ENGINE = Path('rtl/npu/conv/vector_engine.sv')
KEPT = ('state', 'depthwise', 'spatial', 'global_pool', 'load_kind')
DW_STATES = (0, 1, 2, 3, 4, 5, 6, 20, 21, 30, 31, 36, 42, 43, 47)
PROFILES = (
    ('production', True, dict(TILE=16, BUS_WIDTH=64, PE_COUNT=8, WINDOW_LANES=8,
                             SHARED_STORAGE_ENABLE=1, SHARED_QUANT_ENABLE=0,
                             SHARED_STORAGE_ADDR_WIDTH=12, DMA_SIZE=64)),
    ('generic', False, dict(TILE=16, BUS_WIDTH=32, PE_COUNT=16, WINDOW_LANES=4,
                           SHARED_STORAGE_ENABLE=0, SHARED_QUANT_ENABLE=1, DMA_SIZE=64)),
    ('small', False, dict(TILE=2, BUS_WIDTH=32, PE_COUNT=1, WINDOW_LANES=4,
                         SHARED_STORAGE_ENABLE=0, SHARED_QUANT_ENABLE=0, DMA_SIZE=8)),
    ('wide', False, dict(TILE=64, BUS_WIDTH=64, PE_COUNT=16, WINDOW_LANES=16,
                        SHARED_STORAGE_ENABLE=0, SHARED_QUANT_ENABLE=0, DMA_SIZE=256)),
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log, timeout=180):
    with log.open('w') as stream:
        stream.write('$ ' + shlex.join(map(str, command)) + '\n')
        stream.flush()
        result = subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise RuntimeError('状态所有者验证未通过：' + str(log))


def state_enum(source):
    block = re.search(r'typedef enum logic \[5:0\]\s*\{(.*?)\}\s*state_t;', source, re.S)
    assert block
    values, current = {}, -1
    for token in block[1].split(','):
        parts = token.strip().split('=')
        if len(parts) == 2:
            current = int(parts[1].strip().split("'d")[-1])
        else:
            current += 1
        values[parts[0].strip()] = current
    return block[0], values


def audit_changes(reference, selected):
    """确认所有修改均受已经证明的状态条件保护。"""
    old_enum, old_values = state_enum(reference)
    new_enum, new_values = state_enum(selected)
    assert old_values['QUANT_STREAM'] == 37
    assert new_values == {k: v for k, v in old_values.items() if k != 'QUANT_STREAM'}
    expected = reference.replace(old_enum, new_enum)
    expected = expected.replace(' || next_state==QUANT_STREAM', '')
    expected = expected.replace('QUANT_STREAM, AVG_POWER_STORE, AVG_WAIT, POOL_STORE, DW_FINISH:',
                                'AVG_POWER_STORE, AVG_WAIT, POOL_STORE, DW_FINISH:')
    pattern = (r'        QUANT_INIT: begin\n          if \(depthwise\) begin\n'
               r'            if \(!writeback_busy\) begin\n.*?\n            end\n'
               r'          end else if \(!writeback_busy\) begin')
    expected, count = re.subn(pattern, '        QUANT_INIT: begin\n          if (!writeback_busy) begin',
                              expected, flags=re.S)
    assert count == 1
    expected, count = re.subn(r'        QUANT_STREAM: begin\n.*?\n        AVG_START:',
                              '        AVG_START:', expected, flags=re.S)
    assert count == 1
    expected = expected.replace(' || state==QUANT_STREAM', '')
    quant_owner = expected
    flags = 'state_output_init' in selected
    if flags:
        expected = expected.replace('logic [$bits(state_t)+6:0] state_control_value',
                                    'logic [$bits(state_t)+9:0] state_control_value')
        expected = expected.replace('state_control_value = {\n        next_state==EXECUTE_COMMIT,',
            'state_control_value = {\n        next_state==OUTPUT_INIT,\n        next_state==VECTOR_INIT,\n'
            '        next_state==DW_FINISH,\n        next_state==EXECUTE_COMMIT,')
        expected = expected.replace('logic state_failed, state_compute_commit;',
            'logic state_failed, state_compute_commit;\n  logic state_output_init, state_vector_init, state_dw_finish;')
        expected = expected.replace('{state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}',
            '{state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}')
        for flag, name in (('state_output_init', 'OUTPUT_INIT'), ('state_vector_init', 'VECTOR_INIT'),
                           ('state_dw_finish', 'DW_FINISH')):
            expected = re.sub(r'\bstate\s*==\s*' + name + r'\b', flag, expected)
        expected = expected.replace('assert(state_compute_commit == (state==EXECUTE_COMMIT));',
            'assert(state_compute_commit == (state==EXECUTE_COMMIT));\n'
            '      assert(state_output_init == (state==OUTPUT_INIT));\n'
            '      assert(state_vector_init == (state==VECTOR_INIT));\n'
            '      assert(state_dw_finish == (state==DW_FINISH));')
        expected = expected.replace('// 失败标志与状态同时进入寄存器，供中止和排空控制直接使用。',
                                    '// 初始化、提交和失败资格与状态同时保存，直接控制数据选择及排空。')
    extended_bounds = 'logic [INPUT_INDEX_W+1:0] column_difference;' in selected
    if extended_bounds:
        old_bounds = """    wire [INPUT_INDEX_W:0] column_sum={1'b0,win_rsp_col[INPUT_INDEX_W-1:0]}+(INPUT_INDEX_W+1)'(lane);
    assign window_write_valid[lane]=window_response_fire && win_rsp_mask[lane] &&
        win_rsp_col<32'(active) && column_sum<(INPUT_INDEX_W+1)'(active);"""
        new_bounds = """    wire [INPUT_INDEX_W:0] column_sum={1'b0,win_rsp_col[INPUT_INDEX_W-1:0]}+(INPUT_INDEX_W+1)'(lane);
    logic [INPUT_INDEX_W+1:0] column_difference;
    // 扩展减法保留最高借位，完整宽度同时参与四态算术传播。
    assign column_difference = {1'b0,column_sum} - (INPUT_INDEX_W+2)'(active);
    assign window_write_valid[lane]=window_response_fire && win_rsp_mask[lane] &&
        win_rsp_col<32'(active) && column_difference[INPUT_INDEX_W+1];"""
        assert expected.count(old_bounds) == 1
        expected = expected.replace(old_bounds, new_bounds)
    assert expected == selected, '发现不属于本次状态所有者变换的其他修改'
    return {'preserved_state_encodings': new_values, 'registered_initialization_flags': flags,
            'extended_window_bounds': extended_bounds,
            'other_source_statements_identical': True,
            'removed_control_guard': 'state == 37 or (state == 11 and depthwise)'}, quant_owner


def abstract_registers(folder):
    """保留模式和控制状态，其余寄存值及存储输出均成为自由输入。"""
    design = json.loads((folder / 'flat.json').read_text())
    module = design['modules']['vector_engine']
    kept_bits = {bit for name in KEPT for bit in module['netnames'][name]['bits']}
    ports = {name: port for name, port in module['ports'].items() if port['direction'] == 'input'}
    cut, retained = [], []
    for name, cell in list(module['cells'].items()):
        sequential = any(kind in cell['type'] for kind in ('dff', 'latch'))
        if not sequential and not cell['type'].startswith('$mem'):
            continue
        outputs = [bit for port, direction in cell['port_directions'].items()
                   if direction == 'output' for bit in cell['connections'][port]]
        if any(bit in kept_bits for bit in outputs):
            assert all(bit in kept_bits for bit in outputs)
            retained.append({'cell': name, 'type': cell['type'], 'bits': outputs})
            continue
        del module['cells'][name]
        for port, direction in cell['port_directions'].items():
            bits = cell['connections'][port]
            if direction != 'output' or not any(isinstance(bit, int) for bit in bits):
                continue
            label = 'abstract_' + str(len(cut))
            ports[label] = {'direction': 'input', 'bits': bits}
            module['netnames'][label] = {'hide_name': 0, 'bits': bits, 'attributes': {}}
            cut.append({'name': label, 'cell': name, 'type': cell['type'], 'port': port, 'bits': bits})
    module['ports'] = ports
    module['memories'] = {}
    for net in module['netnames'].values():
        net['attributes'].pop('init', None)
    next_bit = max(bit for net in module['netnames'].values()
                   for bit in net['bits'] if isinstance(bit, int)) + 1
    counter = 0

    def gate(kind, left, right=None):
        nonlocal next_bit, counter
        left = [left] if isinstance(left, (int, str)) else left
        right = [right] if isinstance(right, (int, str)) else right
        output, next_bit = next_bit, next_bit + 1
        params = {'A_SIGNED': '0', 'A_WIDTH': format(len(left), '032b'), 'Y_WIDTH': format(1, '032b')}
        connections, directions = {'A': left, 'Y': [output]}, {'A': 'input', 'Y': 'output'}
        if right is not None:
            params.update(B_SIGNED='0', B_WIDTH=format(len(right), '032b'))
            connections['B'], directions['B'] = right, 'input'
        module['cells']['property_' + str(counter)] = dict(
            hide_name=0, type=kind, parameters=params, attributes={},
            connections=connections, port_directions=directions)
        counter += 1
        return output

    def equal(bits, value):
        return gate('$eq', bits, [str((value >> bit) & 1) for bit in range(len(bits))])

    def invert(value):
        return gate('$logic_not', value)

    def both(left, right):
        return gate('$logic_and', left, right)

    def either(left, right):
        return gate('$logic_or', left, right)

    state = module['netnames']['state']['bits']
    depthwise = module['netnames']['depthwise']['bits'][0]
    spatial = module['netnames']['spatial']['bits'][0]
    global_pool = module['netnames']['global_pool']['bits'][0]
    kind = module['netnames']['load_kind']['bits']
    assert len(state) == 6 and len(kind) == 3 and len(retained) == len(KEPT)
    allowed = gate('$reduce_or', [equal(state, value) for value in DW_STATES])
    loading = gate('$reduce_or', [equal(state, value) for value in (4, 5, 47)])
    mode = both(spatial, invert(global_pool))
    flow = both(allowed, either(invert(loading), invert(kind[2])))
    property_bit = both(either(invert(depthwise), both(mode, flow)), invert(equal(state, 37)))
    module['ports']['o_property'] = {'direction': 'output', 'bits': [property_bit]}
    module['netnames']['o_property'] = {'hide_name': 0, 'bits': [property_bit], 'attributes': {}}
    for name in KEPT:
        bits = module['netnames'][name]['bits']
        module['ports']['o_' + name] = {'direction': 'output', 'bits': bits}
    (folder / 'abstract.json').write_text(json.dumps(design))
    record = dict(flat_sha256=sha(folder / 'flat.json'), kept_register_names=KEPT,
                  retained=retained, abstracted=cut, allowed_depthwise_states=DW_STATES)
    (folder / 'abstraction.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def prove_reachability(source_root, engine, folder, fpga, parameters, sources):
    folder.mkdir(parents=True, exist_ok=True)
    arguments = ['read_slang', '--top', 'vector_engine', '-I', str(source_root / 'include'),
                 '-I', str(source_root / 'rtl/npu/ps_compact'), '-D', 'SYNTHESIS=1', '-D',
                 'XILINX_FPGA=1' if fpga else 'ASIC_SYNTHESIS=1']
    arguments += [f'-G{name}={value}' for name, value in parameters.items()]
    arguments += [str(engine if path == ENGINE else source_root / path) for path in sources]
    script = folder / 'elaborate.ys'
    script.write_text(shlex.join(arguments) + '\n'
                      'read_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\n'
                      'read_verilog -lib -overwrite +/xilinx/cells_xtra.v\n'
                      'hierarchy -check -top vector_engine\nproc\nflatten\nopt -keepdc\n'
                      'select vector_engine\nwrite_json -selected ' + str(folder / 'flat.json') + '\n')
    worker = [sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--worker']
    run(worker + [script], folder / 'elaborate.log')
    abstraction = abstract_registers(folder)
    script = folder / 'proof.ys'
    script.write_text('read_json ' + str(folder / 'abstract.json') + '\n'
                      'hierarchy -top vector_engine\nopt -full\nasync2sync\nopt -full\n'
                      'sat -verify -tempinduct -seq 4 -set-at 1 rst_n 0 -prove o_property 1 '
                      '-show o_state,o_depthwise,o_spatial,o_global_pool,o_load_kind\n')
    run(worker + [script], folder / 'proof.log')
    log = (folder / 'proof.log').read_text()
    assert 'Induction step proven: SUCCESS!' in log
    return dict(passed=True, induction_length=int(re.findall(r'Trying induction with length (\d+)', log)[-1]),
                retained_register_groups=len(abstraction['retained']),
                abstracted_state_outputs=len(abstraction['abstracted']),
                proof_log_sha256=sha(folder / 'proof.log'), abstraction_sha256=sha(folder / 'abstraction.json'))


def check_control_words(reference, selected, folder, iverilog, vvp):
    old_enum, values = state_enum(reference)
    functions = []
    for label, source in (('reference', reference), ('selected', selected)):
        function = re.search(r'function automatic logic .*? state_control_value\(.*?endfunction', source, re.S)[0]
        function = function.replace('state_control_value', label + '_control')
        function = function.replace('input state_t next_state', 'input logic [5:0] next_state')
        functions.append(function)
    expressions = set(re.findall(r'<=state_control_value\((.*?)\);', selected))
    pairs = []
    for expression in expressions:
        if '?' in expression:
            match = re.search(r'\?\s*(\w+)\s*:\s*(\w+)\s*$', expression)
            assert match
            pairs.append((values[match[1]], values[match[2]]))
        else:
            assert expression in values and values[expression] != 37
    statements = ['next_state = 6\'d' + str(value) + '; check_word();' for value in values.values() if value != 37]
    for left, right in sorted(set(pairs)):
        for condition in ("1'b0", "1'b1", "1'bx", "1'bz"):
            statements.append(f"next_state = {condition} ? 6'd{left} : 6'd{right}; check_word();")
    bench = folder / 'control_four_state.sv'
    width = 16 if 'state_output_init' in selected else 13
    bench.write_text('module tb;\n' + old_enum + '\n' + '\n'.join(functions) + f'''
logic [5:0] next_state;
wire [{width-1}:0] selected_word = selected_control(next_state);
integer checks=0;
task check_word;
begin
    #1;
    if(reference_control(next_state) !== selected_word[12:0]) $fatal(1,"control word %b",next_state);
    checks=checks+1;
end
endtask
initial begin
''' + '\n'.join(statements) + '''
    $display("VECTOR_QUANT_OWNER_CONTROL_PASS checks=%0d",checks);
    $finish;
end
endmodule
''')
    run([iverilog, '-g2012', '-s', 'tb', '-o', folder / 'control.vvp', bench], folder / 'control_compile.log')
    run([vvp, folder / 'control.vvp'], folder / 'control_four_state.log')
    assert 'VECTOR_QUANT_OWNER_CONTROL_PASS' in (folder / 'control_four_state.log').read_text()
    return dict(passed=True, actual_conditional_pairs=len(set(pairs)), comparisons=len(statements),
                four_state_condition_values=['0', '1', 'X', 'Z'], log_sha256=sha(folder / 'control_four_state.log'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path)
    parser.add_argument('--reference-revision', default='cedf4ed33661a53c8194eca1d484cdc2279d7549')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--iverilog', default='iverilog')
    parser.add_argument('--vvp', default='vvp')
    args = parser.parse_args()
    source, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    selected_path = source / ENGINE
    if args.reference_root:
        reference_path = args.reference_root.resolve() / ENGINE
    else:
        reference_path = out / 'reference_engine.sv'
        reference_path.write_bytes(subprocess.check_output(
            ['git', 'show', args.reference_revision + ':' + str(ENGINE)], cwd=ROOT))
    reference, selected = reference_path.read_text(), selected_path.read_text()
    audit, quant_owner = audit_changes(reference, selected)
    case = json.loads((ROOT / 'test/vector_engine/production_synthesis_cases.json').read_text())['vector']
    sources = list(dict.fromkeys([Path(path) for path in case['sources']] +
        [path.relative_to(source) for path in sorted((source / 'rtl/common').rglob('*'))
         if path.suffix in ('.v', '.sv')]))
    hashes = {str(path): sha(source / path) for path in sources}
    report = dict(passed=False, source_sha256=sha(selected_path), reference_sha256=sha(reference_path),
                  dependency_sha256=hashes, source_audit=audit, profiles=[],
                  input_constraints='rst_n=0 at the first sampled cycle; all other inputs and subsequent reset values are free',
                  abstraction='Only state, depthwise, spatial, global_pool and load_kind remain sequential; all other register and memory outputs are free inputs')
    report['control_words'] = check_control_words(reference, selected, out, args.iverilog, args.vvp)
    if audit['registered_initialization_flags']:
        intermediate = out / 'quant_owner_source' / ENGINE
        intermediate.parent.mkdir(parents=True, exist_ok=True)
        intermediate.write_text(quant_owner)
        flag_out = out / 'initialization_flags'
        run([sys.executable, ROOT / 'test/vector_control_flags/run.py',
             '--source-root', source, '--reference-root', out / 'quant_owner_source',
             '--out', flag_out, '--iverilog', args.iverilog, '--vvp', args.vvp],
            out / 'initialization_flags.log')
        report['initialization_flags'] = json.loads((flag_out / 'summary.json').read_text())
    for name, fpga, parameters in PROFILES:
        row = dict(profile=name, parameters=parameters, fpga=fpga)
        for label, engine in (('reference', reference_path), ('selected', selected_path)):
            row[label] = prove_reachability(source, engine, out / name / label, fpga, parameters, sources)
        report['profiles'].append(row)
        print(json.dumps(row), flush=True)
    assert reference == reference_path.read_text() and selected == selected_path.read_text()
    assert hashes == {str(path): sha(source / path) for path in sources}
    report.update(passed=True, test_sha256=sha(Path(__file__)))
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
