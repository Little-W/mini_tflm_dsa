#!/usr/bin/env python3
"""验证有符号裁剪比较与列结束比较的数值、四态行为和完整算术通道。"""
from concurrent.futures import ThreadPoolExecutor
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
REFERENCE = 'a235227e'
LANE = 'rtl/npu/writeback/requant_compute_lane.sv'
VECTOR = 'rtl/npu/writeback/vec_requant.sv'
MODES = [('generic', []), ('synthesis', ['-DSYNTHESIS=1']),
         ('fpga', ['-DXILINX_FPGA=1']),
         ('fpga_synthesis', ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'])]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command, log, timeout=600):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    revision = subprocess.check_output(['git', 'rev-parse', REFERENCE+'^{commit}'], cwd=ROOT, text=True).strip()
    originals = {name: subprocess.check_output(['git', 'show', f'{revision}:{name}'], cwd=ROOT, text=True)
                 for name in (LANE, VECTOR)}
    reference = out/'reference_lane.sv'
    reference.write_text(originals[LANE])
    dependencies = resolve([ROOT/LANE, ROOT/VECTOR], ROOT)
    hashes = {str(path.relative_to(ROOT)): sha(path) for path in dependencies}

    def parent(job):
        label, flags, delayed = job
        folder = out/(label+'_delayed'+str(delayed))
        folder.mkdir(exist_ok=True)
        commands = []
        for name, source in [('reference', reference), ('candidate', ROOT/LANE)]:
            sources = resolve([source], ROOT)
            commands += ['read_slang --top requant_compute_lane '+shlex.join(
                [*flags, f'-Gp_delayed_parameters={delayed}', *map(str, sources)]),
                'setattr -mod -unset keep_hierarchy', 'setattr -unset keep_hierarchy',
                'prep -top requant_compute_lane -flatten', 'memory_map', 'async2sync', 'opt -full',
                'rename -top '+name, 'design -stash '+name]
        private = folder/'private_signals.txt'
        # 这些分组信号仅供未知输入分支使用；公开裁剪结果始终参与逐周期比较。
        private.write_text('\n'.join(f'g_bound[{bound}].{signal}' for bound in range(2)
            for signal in ('equal_group', 'greater_group', 'greater_selected'))+'\n')
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from candidate -as candidate candidate',
                     'equiv_make -blacklist '+shlex.quote(str(private))+' reference candidate proof',
                     'hierarchy -top proof', 'equiv_simple -short -seq 2', 'opt_clean',
                     'equiv_induct -seq 3', 'equiv_status -assert']
        script, log = folder/'proof.ys', folder/'formal.log'
        script.write_text('\n'.join(commands)+'\n')
        execute([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
        assert 'Equivalence successfully proven!' in log.read_text()
        nodes = re.findall(r'Of those cells (\d+) are proven and (\d+) are unproven', log.read_text())[-1]
        assert int(nodes[1]) == 0
        print(folder.name+' PASS', flush=True)
        return {'mode': label, 'delayed_parameters': delayed, 'passed': True,
                'proven_equivalent_nodes': int(nodes[0]), 'external_inputs_constrained': False,
                'all_public_outputs_compared': True, 'formal_log_sha256': sha(log)}

    ports = '''(input logic clk,rst_n,i_en,i_clear,i_valid,i_lane_enable,
input logic signed [34:0] rounded_q,
input logic signed [31:0] i_activation_min,i_activation_max,
output logic o_valid,output logic signed [7:0] o_s8,
output logic signed [15:0] o_s16,output wire [1:0] proof_bound_less);'''
    units = []
    for label, source in [('reference', originals[LANE]), ('candidate', (ROOT/LANE).read_text())]:
        first = source.index('    for (genvar bound = 0; bound < 2; bound++)')
        last = source.index('\nendmodule', first)
        unit = out/(label+'_tail.sv')
        unit.write_text('module '+label+ports+'''
localparam p_stages=7;logic [6:0] valid_q;logic [5:0] lane_enable_q;logic [1:0] bound_less;
assign o_valid=valid_q[6];assign proof_bound_less=bound_less;
'''+source[first:last]+'\nendmodule\n')
        units.append(unit)
    bench = out/'tb.sv'
    bench.write_text('''module tb;
reg clk=0,rst_n=0,i_en=1,i_clear=0,i_valid=0,i_lane_enable=0;
reg signed [34:0] rounded_q;
reg signed [31:0] i_activation_min,i_activation_max;
wire [26:0] actual,expected;
integer checks=0;
reference ref_dut(.*,.o_valid(expected[0]),.o_s8(expected[8:1]),.o_s16(expected[24:9]),.proof_bound_less(expected[26:25]));
candidate dut(.*,.o_valid(actual[0]),.o_s8(actual[8:1]),.o_s16(actual[24:9]),.proof_bound_less(actual[26:25]));
function automatic reg symbol(input integer v);
case(v%4)0:symbol=0;1:symbol=1;2:symbol=1'bx;3:symbol=1'bz;endcase
endfunction
task check;begin
if(actual!==expected)$fatal(1,"裁剪结果或状态不同 sample=%0d",checks);checks++;
end endtask
initial begin
rounded_q=0;i_activation_min=-128;i_activation_max=127;#1;clk=1;#1;clk=0;
for(integer sample=0;sample<65536;sample++)begin
rst_n=(sample%1024==0)?0:1;i_en=symbol(sample>>2);
i_clear=(sample%1024<768)?0:symbol(sample>>4);
i_valid=symbol(sample>>6);i_lane_enable=symbol(sample>>8);
rounded_q={$urandom,$urandom};i_activation_min=$urandom;i_activation_max=$urandom;
case(sample%8)
0:begin i_activation_min=-128;i_activation_max=127;end
1:begin i_activation_min=-32768;i_activation_max=32767;end
2:rounded_q[34:32]=3'bxxx;
3:rounded_q[sample%35]=1'bz;
4:i_activation_min[sample%32]=1'bx;
5:i_activation_max[sample%32]=1'bz;
6:rounded_q='x;
default:begin end
endcase
#1;check();clk=1;#1;check();clk=0;
end
$display("PASS comparisons=%0d",checks);$finish;
end
endmodule
''')

    def four_state(mode):
        label, flags = mode
        folder = out/(label+'_four_state')
        folder.mkdir(exist_ok=True)
        sources = resolve(units, ROOT)
        simulation = folder/'simulation'
        execute(['iverilog', '-g2012', *flags, '-s', 'tb', '-o', simulation, *sources, bench], folder/'compile.log')
        execute(['vvp', simulation], folder/'run.log')
        assert 'PASS comparisons=131072' in (folder/'run.log').read_text()
        return {'mode': label, 'passed': True, 'comparisons': 131072, 'log_sha256': sha(folder/'run.log')}

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        parents = list(pool.map(parent, [(label, flags, delayed) for label, flags in MODES for delayed in (0, 1)]))
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        four = list(pool.map(four_state, MODES))

    # 列结束 helper 连接回已证明的完整相等表达式，检查父模块其余源码逐字保持相同。
    current = (ROOT/VECTOR).read_text()
    declaration = '  logic        unused_last_col_group;\n'
    column = '''  // 列坐标分段比较后归并，末列条件只参与后续状态选择。
  requant_group_last #(.p_tile_width(TILE_CNT_W)) u_column_last (
      .i_row(tile_col), .i_last_row(last_col_tile), .i_mask('0),
      .o_last_tile(cur_last_col_tile), .o_last_group(unused_last_col_group)
  );

'''
    assert current.count(declaration) == 1 and current.count(column) == 1
    normalized = current.replace(declaration, '').replace(column, '')
    anchor = '    step_row_in_group = !cur_last_row_in_group;'
    assert normalized.count(anchor) == 1
    normalized = normalized.replace(anchor, '    cur_last_col_tile = (tile_col == last_col_tile);\n'+anchor)
    assert normalized == originals[VECTOR]
    previous = json.loads((ROOT/'test/requant_parallel_prefix/validation.json').read_text())
    assert previous['passed'] and previous['production_composition']['passed']
    for row in previous['profiles']:
        if row['kind'] == 'group' and row['width'] == 16:
            assert row['passed']
    unchanged = {}
    for source in dependencies:
        relative = str(source.relative_to(ROOT))
        if relative in (LANE, VECTOR):
            continue
        original = subprocess.check_output(['git', 'show', f'{revision}:{relative}'], cwd=ROOT)
        assert original == source.read_bytes(), relative
        unchanged[relative] = sha(source)
    assert hashes == {name: sha(ROOT/name) for name in hashes}
    report = {'passed': True, 'reference_commit': revision, 'source_sha256': hashes,
              'parents': parents, 'four_state': four, 'four_state_comparisons': sum(x['comparisons'] for x in four),
              'production_composition': {'passed': True, 'method': 'interface_equivalence_and_combinational_substitution',
                  'unchanged_dependency_sha256': unchanged, 'unchanged_parent_after_column_substitution': True,
                  'column_helper': 'requant_group_last(p_tile_width=16), o_last_tile',
                  'column_proof_sha256': sha(ROOT/'test/requant_parallel_prefix/validation.json'),
                  'arithmetic_delayed_parameters_proven': [0, 1], 'external_inputs_constrained': False,
                  'all_public_cycle_behaviors_preserved': True}, 'test_sha256': sha(Path(__file__))}
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'passed': True, 'parent_proofs': len(parents), 'four_state_comparisons': report['four_state_comparisons']}), flush=True)


if __name__ == '__main__':
    main()
