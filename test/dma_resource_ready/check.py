#!/usr/bin/env python3
"""证明 DMA 资源资格与完整读写仲裁器在任意输入下保持逐周期行为。"""
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
ARBITER = 'rtl/npu/dma/axi_block_dma_arbiter.sv'
DMA = 'rtl/npu/dma/axi_dual_block_dma.sv'
PACKAGE = 'rtl/npu/conv/conv_im2col_pkg.sv'
TOP = 'axi_block_dma_arbiter'
FORMAL = runpy.run_path(str(ROOT / 'test/dma_return_admission/run_arbiter_formal.py'))
FLAGS = ('conv_cfg_valid', 'conv_active', 'conv_pending', 'linear_busy',
         'linear_finish', 'win_busy', 'fe_busy', 'job_conv', 'linear_start_ready',
         'fe_output_valid', 'guard_idle', 'mux_idle', 'rd_im2col')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reference(revision, name):
    return subprocess.check_output(['git', 'show', revision + ':' + name],
                                   cwd=ROOT, text=True)


def assignment(text, name):
    match = re.search(r'\bassign\s+' + name + r'\s*=.*?;', text, re.S)
    if match is None:
        raise ValueError('Missing production assignment: ' + name)
    return match[0]


def functional_tokens(text):
    return re.sub(r'\s+', '', re.sub(r'//[^\n]*|/\*.*?\*/', '', text, flags=re.S))


def ready_model(name, text):
    names = ['image_start_ready', 'rd_start_ready']
    if re.search(r'\bassign\s+rd_resource_ready\s*=', text):
        names = ['image_resource_ready', 'image_start_ready',
                 'rd_resource_ready', 'rd_start_ready']
    body = '\n'.join(assignment(text, item) for item in names)
    return f'''// 由生产 DMA 表达式构成的完整命令接收资格。
module {name} (
    input wire [{len(FLAGS)-1}:0] conditions, // 配置、资源状态与命令类型
    output wire [1:0] ready // 图像命令与当前类型命令的接收资格
);
    wire {', '.join(FLAGS)};
    wire image_resource_ready, image_start_ready, rd_resource_ready, rd_start_ready;
    assign {{{', '.join(FLAGS)}}} = conditions;
    {body}
    assign ready = {{image_start_ready, rd_start_ready}};
endmodule
'''


def ready_proof(out, old, current):
    source = out / 'ready.sv'
    source.write_text(ready_model('ready_reference', old) + ready_model('ready_current', current) +
        f'''// 比较全部命令接收条件，不限制外部输入或内部资源状态。
module proof (
    input wire [{len(FLAGS)-1}:0] conditions, // 完整资源条件
    output wire equal // 两组接收资格完全相等
);
    wire [1:0] reference_ready, current_ready;
    ready_reference reference_design(conditions, reference_ready);
    ready_current current_design(conditions, current_ready);
    assign equal = reference_ready === current_ready;
endmodule
''')
    log = FORMAL['run'](out, 'ready_formal', [
        'read_slang --top proof ' + shlex.quote(str(source)),
        'prep -top proof -flatten', 'check -assert',
        'sat -verify -prove equal 1 -show-inputs -show-outputs'])
    assert 'SUCCESS!' in log.read_text()
    tb = out / 'ready_tb.sv'
    tb.write_text(f'''// 固定种子覆盖全部二态输入及逐位、交错和随机四态输入。
module tb;
    reg [{len(FLAGS)-1}:0] conditions;
    wire equal;
    integer checks = 0;
    reg [31:0] random_state = 32'h6d4a2e71;
    proof comparison(conditions, equal);
    task automatic check;
        #1;
        if (equal !== 1'b1) $fatal(1, "DMA ready differs: %b", conditions);
        checks++;
    endtask
    initial begin
        for (integer sample = 0; sample < (1 << {len(FLAGS)}); sample++) begin
            conditions = {len(FLAGS)}'(sample);
            check();
        end
        for (integer sample = 0; sample < 262144; sample++) begin
            for (integer bit_index = 0; bit_index < {len(FLAGS)}; bit_index++) begin
                random_state = random_state ^ (random_state << 13);
                random_state = random_state ^ (random_state >> 17);
                random_state = random_state ^ (random_state << 5);
                case (random_state[1:0])
                    0: conditions[bit_index] = 1'b0;
                    1: conditions[bit_index] = 1'b1;
                    2: conditions[bit_index] = 1'bx;
                    3: conditions[bit_index] = 1'bz;
                endcase
            end
            check();
        end
        $display("DMA_RESOURCE_READY_PASS checks=%0d", checks);
        $finish;
    end
endmodule
''')
    executable = out / 'ready.vvp'
    with (out / 'ready_compile.log').open('w') as stream:
        subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', executable, source, tb],
                       stdout=stream, stderr=subprocess.STDOUT, check=True)
    result = subprocess.check_output(['vvp', executable], text=True)
    simulation = out / 'ready_four_state.log'
    simulation.write_text(result)
    checks = 262144 + (1 << len(FLAGS))
    assert f'PASS checks={checks}' in result
    return {'passed': True, 'inputs_constrained': False, 'four_state_comparisons': checks,
            'formal_log_sha256': digest(log), 'simulation_log_sha256': digest(simulation),
            'model_sha256': digest(source), 'testbench_sha256': digest(tb)}


def connected_ready_boundary(path):
    """用实际 DMA 配置关系连接返回资格，其余 DMA 返回端口保持任意输入。"""
    design = json.loads(path.read_text())
    module = design['modules'][TOP]
    ports, nets, cells = module['ports'], module['netnames'], module['cells']
    next_bit = max(bit for net in nets.values() for bit in net['bits']
                   if isinstance(bit, int)) + 1
    resource = 'formal_dma_rd_resource_ready'
    if resource not in ports:
        ports[resource] = {'direction': 'input', 'bits': [next_bit]}
        nets[resource] = {'hide_name': 0, 'bits': [next_bit], 'attributes': {}}
        next_bit += 1
    ready = ports.pop('formal_dma_rd_start_ready')['bits']
    configuration = ports['formal_dma_conv_cfg_valid']['bits']
    cells['resource_configuration_invert'] = {
        'type': '$not', 'parameters': {'A_SIGNED': 0, 'A_WIDTH': 1, 'Y_WIDTH': 1},
        'attributes': {}, 'port_directions': {'A': 'input', 'Y': 'output'},
        'connections': {'A': configuration, 'Y': [next_bit]},
    }
    cells['resource_command_ready'] = {
        'type': '$and', 'parameters': {'A_SIGNED': 0, 'B_SIGNED': 0,
                                      'A_WIDTH': 1, 'B_WIDTH': 1, 'Y_WIDTH': 1},
        'attributes': {}, 'port_directions': {'A': 'input', 'B': 'input', 'Y': 'output'},
        'connections': {'A': [next_bit], 'B': ports[resource]['bits'], 'Y': ready},
    }
    path.write_text(json.dumps(design) + '\n')
    return {name: (port['direction'], len(port['bits'])) for name, port in ports.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='7c2942ea')
    parser.add_argument('--dma-reference', default='8009b2f7')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    hashes = {name: digest(ROOT / name) for name in (ARBITER, DMA, PACKAGE)}
    current = (ROOT / ARBITER).read_text()
    previous = reference(args.reference, ARBITER)
    reconstructed = current.replace('rd_dma_start_ready, rd_dma_resource_ready', 'rd_dma_start_ready')
    reconstructed = re.sub(r'\s*\.rd_resource_ready\s*\(rd_dma_resource_ready\),', '', reconstructed)
    reconstructed = reconstructed.replace(assignment(current, 'rd_reservation_space'),
                                           assignment(previous, 'rd_reservation_space'))
    assert functional_tokens(reconstructed) == functional_tokens(previous)
    assert len(re.findall(r'\brd_reservation_space\b', current)) == 3
    dma = (ROOT / DMA).read_text()
    assert functional_tokens(assignment(dma, 'rd_start_ready')) == \
        'assignrd_start_ready=!conv_cfg_valid&&rd_resource_ready;'
    report = {'passed': False, 'source_sha256': hashes,
              'reference_commit': subprocess.check_output(['git', 'rev-parse', args.reference],
                                                          cwd=ROOT, text=True).strip(),
              'dma_reference_commit': subprocess.check_output(['git', 'rev-parse', args.dma_reference],
                                                              cwd=ROOT, text=True).strip(),
              'unchanged_arbiter_functional_tokens_verified': True,
              'ready_expression': ready_proof(out, reference(args.dma_reference, DMA), dma),
              'profiles': []}
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    model = out / 'lut_models.v'
    models = [re.search(r'^module ' + primitive + r'\b.*?^endmodule', library.read_text(),
                        re.M | re.S)[0] for primitive in ('LUT6', 'LUT6_2')]
    model.write_text('\n'.join(re.sub(r'\bspecify\b.*?\bendspecify\b', '', item, flags=re.S)
                               for item in models) + '\n')
    snapshots = {}
    for label in ('reference', 'current'):
        folder = out / label
        folder.mkdir(exist_ok=True)
        snapshots[label] = []
        for name in (PACKAGE, ARBITER, DMA):
            content = previous if name == ARBITER and label == 'reference' else (ROOT / name).read_text()
            if name == DMA:
                header_end = re.search(r'^\s*\);', content, re.M).end()
                content = content[:header_end] + '\nendmodule\n'
            path = folder / Path(name).name
            path.write_text(content)
            snapshots[label].append(path)
    profiles = [(bus, quant, True) for bus in (32, 64, 128) for quant in (0, 1)]
    profiles.append((64, 1, False))
    for bus, quant, fpga in profiles:
        name = f'{"fpga" if fpga else "generic"}_bus{bus}_quant{quant}'
        options = ['-GSIZE=16', '-GDMA_SIZE=64', '-GCACHE_BLOCKS=64', f'-GBUS_WIDTH={bus}',
                   f'-GENABLE_QUANT_CLIENT={quant}',
                   '-DXILINX_FPGA=1' if fpga else '-DASIC_SYNTHESIS=1']
        signatures = {}
        for label in ('reference', 'current'):
            raw, expanded = out / f'{name}_{label}.json', out / f'{name}_{label}_expanded.json'
            commands = [f'read_slang --keep-hierarchy --top {TOP} ' +
                        shlex.join(options + [str(path) for path in [*snapshots[label], model]]),
                        'blackbox axi_dual_block_dma*', f'prep -top {TOP} -flatten',
                        'memory_map', 'async2sync', 'opt_clean', 'write_json ' + shlex.quote(str(raw))]
            FORMAL['run'](out, f'{name}_{label}_elaborate', commands)
            FORMAL['expand_dma_ports'](raw, expanded)
            signatures[label] = connected_ready_boundary(expanded)
        assert signatures['reference'] == signatures['current']
        commands = []
        for label in ('reference', 'current'):
            commands += ['read_json ' + shlex.quote(str(out / f'{name}_{label}_expanded.json')),
                         f'prep -top {TOP}', 'rename -hide w:rd_reservation_space',
                         f'rename {TOP} {label}', f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                     'opt_merge', 'equiv_simple -short -seq 1', 'opt_clean',
                     'equiv_induct -seq 2', 'equiv_status -assert']
        log = FORMAL['run'](out, name, commands)
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', log.read_text())
        assert match and int(match[2]) == 0 and 'Equivalence successfully proven' in log.read_text()
        row = {'passed': True, 'bus_width': bus, 'quant_client': quant, 'fpga': fpga,
               'equivalent_bits': int(match[1]), 'proof_log_sha256': digest(log),
               'dma_resource_condition': 'rd_start_ready = !conv_cfg_valid && rd_resource_ready',
               'public_inputs_constrained': False, 'other_dma_returns_constrained': False,
               'scope': 'Complete arbiter state, public outputs, and every DMA input port'}
        report['profiles'].append(row)
        print(json.dumps(row), flush=True)
    assert hashes == {name: digest(ROOT / name) for name in hashes}
    report.update(passed=True, checker_sha256=digest(Path(__file__)))
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
