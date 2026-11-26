#!/usr/bin/env python3
"""验证量化舍入进位与分组比较的完整输入、四态结果及父模块逐周期等价。"""
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
REFERENCE = 'd035fedc'
SOURCES = {'round': 'rtl/npu/writeback/requant_round_add.sv',
           'group': 'rtl/npu/writeback/requant_group_last.sv'}
PROFILES = [('round', width, low) for width, low in
            [(2, 1), (3, 2), (16, 8), (32, 16), (33, 17), (35, 17), (35, 18), (46, 23)]]
PROFILES += [('group', width, 0) for width in (1, 4, 8, 16, 32)]


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
    parser.add_argument('--skip-parent', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(['git', 'rev-parse', REFERENCE+'^{commit}'],
                                      cwd=ROOT, text=True).strip()
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    references, hashes = {}, {}
    for kind, relative in SOURCES.items():
        path = out/(kind+'_reference.sv')
        path.write_bytes(subprocess.check_output(['git', 'show', f'{revision}:{relative}'], cwd=ROOT))
        references[kind] = path
        for source in resolve([ROOT/relative], ROOT):
            hashes[str(source.relative_to(ROOT))] = sha(source)

    def helper(job):
        kind, width, low, synthesis = job
        name = f'{kind}{width}_low{low}_'+('synthesis' if synthesis else 'generic')
        folder = out/name
        folder.mkdir(exist_ok=True)
        top = 'requant_round_add' if kind == 'round' else 'requant_group_last'
        options = ['-DSYNTHESIS=1'] if synthesis else []
        parameters = [f'-Gp_width={width}', f'-Gp_low_width={low}'] if kind == 'round' else [f'-Gp_tile_width={width}']
        commands = []
        for label, source in [('reference', references[kind]), ('candidate', ROOT/SOURCES[kind])]:
            dependencies = resolve([source], ROOT)
            commands += ['read_slang --top '+top+' '+shlex.join(options+parameters+list(map(str, dependencies))),
                         'setattr -mod -unset keep_hierarchy', 'setattr -unset keep_hierarchy',
                         'prep -top '+top+' -flatten', 'opt -full',
                         'rename -top '+label, 'design -stash '+label]
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from candidate -as candidate candidate',
                     'equiv_make reference candidate proof', 'hierarchy -top proof',
                     'equiv_simple', 'equiv_status -assert']
        script, log = folder/'proof.ys', folder/'formal.log'
        script.write_text('\n'.join(commands)+'\n')
        execute([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
        assert 'Equivalence successfully proven!' in log.read_text()
        reference = folder/'reference.sv'
        reference.write_text(references[kind].read_text().replace('module '+top, 'module reference'))
        sources = resolve([ROOT/SOURCES[kind], reference], ROOT)
        if kind == 'round':
            declarations = f'wire [{width-1}:0] actual,expected;\nreg increment;'
            connections = '.i_a(a),.i_b(b),.i_increment(increment),.o_sum(actual)'
            parameters_text = f'#(.p_width({width}),.p_low_width({low}))'
            perturb = "increment=1'bx;verify();increment=1'bz;verify();increment=sample[0];"
        else:
            declarations = f'wire [1:0] actual,expected;\nreg [{width-1}:0] mask,saved_mask;'
            connections = '.i_row(a),.i_last_row(b),.i_mask(mask),.o_last_tile(actual[0]),.o_last_group(actual[1])'
            parameters_text = f'#(.p_tile_width({width}))'
            perturb = f"mask[sample%{width}]=1'bx;verify();mask=saved_mask;mask[sample%{width}]=1'bz;verify();mask=saved_mask;"
        init = 'increment=sample[0];' if kind == 'round' else 'mask={$urandom,$urandom};if(sample%5==0)mask=\'1;if(sample%5==1)mask=\'0;saved_mask=mask;'
        bench = folder/'tb.sv'
        bench.write_text(f'''module tb;
    reg [{width-1}:0] a,b,saved_a,saved_b;
    {declarations}
    integer checks=0,seed=20261126;
    {top} {parameters_text} dut({connections});
    reference {parameters_text} ref_dut({connections.replace('actual','expected')});
    task verify; begin
        #1;if(actual !== expected)$fatal(1,"量化前缀运算结果不一致");checks++;
    end endtask
    initial begin
        seed=$urandom(seed);
        for(integer sample=0;sample<16384;sample++)begin
            a={{$urandom,$urandom}};b={{$urandom,$urandom}};{init}
            case(sample%8)
                0:a='0;1:a='1;2:b='0;3:b='1;4:b=a;5:b=~a;
                default:begin end
            endcase
            verify();saved_a=a;saved_b=b;
            a[sample%{width}]=1'bx;verify();a=saved_a;
            b[sample%{width}]=1'bz;verify();b=saved_b;
            {perturb}
        end
        $display("PASS checks=%0d",checks);$finish;
    end
endmodule
''')
        binary = folder/'simulation'
        execute(['iverilog', '-g2012', *(['-DSYNTHESIS=1'] if synthesis else []),
                 '-s', 'tb', '-o', binary, *sources, bench], folder/'compile.log')
        execute(['vvp', binary], folder/'four_state.log')
        comparisons = 16384*5
        assert f'PASS checks={comparisons}' in (folder/'four_state.log').read_text()
        print(name+' PASS', flush=True)
        return {'kind': kind, 'width': width, 'low_width': low, 'synthesis': synthesis,
                'passed': True, 'four_state_comparisons': comparisons,
                'formal_log_sha256': sha(log), 'four_state_log_sha256': sha(folder/'four_state.log')}

    def parent(job):
        top, options, synthesis, name = job
        folder = out/name
        folder.mkdir(exist_ok=True)
        flags = options+(['-DSYNTHESIS=1'] if synthesis else [])
        relative = 'rtl/npu/writeback/'+top+'.sv'
        commands, models, states = [], {}, {}
        for label in ('reference', 'candidate'):
            helpers = list(references.values()) if label == 'reference' else [ROOT/value for value in SOURCES.values()]
            dependencies = resolve([ROOT/relative, *helpers], ROOT)
            for source in dependencies:
                if source.is_relative_to(ROOT) and not source.is_relative_to(out):
                    hashes[str(source.relative_to(ROOT))] = sha(source)
            models[label] = folder/(label+'_model.il')
            commands += ['read_slang --top '+top+' '+shlex.join(flags+list(map(str, dependencies))),
                         'setattr -mod -unset keep_hierarchy', 'setattr -unset keep_hierarchy',
                         'prep -top '+top+' -flatten', 'memory_map', 'async2sync', 'opt -full',
                         'rename -top '+label, 'write_rtlil '+shlex.quote(str(models[label])),
                         'design -reset']
        prepare = folder/'prepare.ys'
        prepare.write_text('\n'.join(commands)+'\n')
        execute([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', prepare],
                folder/'prepare.log', timeout=900)
        # 异步复位转换保留的原始寄存状态参与逐周期对应，复位输出选择另行证明。
        for label, model in models.items():
            states[label] = {}
            with model.open() as stream:
                for line in stream:
                    if not line.startswith('  wire ') or '$auto$async2sync.cc:' not in line:
                        continue
                    raw = line.split('# ', 1)[-1].strip() if '# ' in line else line.split()[-1]
                    width = re.search(r'\bwidth (\d+)', line)
                    states[label][raw] = int(width[1]) if width else 1
        common_states = sorted(set(states['reference']) & set(states['candidate']))
        assert all(states['reference'][signal] == states['candidate'][signal] for signal in common_states)
        private = folder/'private_signals.txt'
        # 该组合别名的未使用高位可在分组比较后删除，公开输出仍全部参与检查。
        private.write_text('row_offset_in_group\n' if top == 'vec_requant' else '')
        commands = []
        for label in ('reference', 'candidate'):
            commands += ['read_rtlil '+shlex.quote(str(models[label])), 'design -stash '+label]
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from candidate -as candidate candidate',
                     'equiv_make -blacklist '+shlex.quote(str(private))+' reference candidate proof',
                     'hierarchy -top proof', 'cd proof']
        commands += ['equiv_add '+signal+'_gold '+signal+'_gate' for signal in common_states]
        commands += ['equiv_struct', 'equiv_simple -undef -short -seq 2', 'opt_clean',
                     'equiv_induct -undef -seq 3', 'equiv_simple -undef -short -seq 2',
                     'equiv_status -assert']
        script, log = folder/'proof.ys', folder/'formal.log'
        script.write_text('\n'.join(commands)+'\n')
        execute([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log, timeout=900)
        assert 'Equivalence successfully proven!' in log.read_text()
        counts = re.findall(r'Of those cells (\d+) are proven and (\d+) are unproven', log.read_text())[-1]
        assert int(counts[1]) == 0
        model_hashes = {label: sha(model) for label, model in models.items()}
        for model in models.values():
            model.unlink()
        print(name+' PASS', flush=True)
        return {'top': top, 'options': flags, 'passed': True, 'proven_equivalent_nodes': int(counts[0]),
                'external_inputs_constrained': False, 'all_public_outputs_compared': True,
                'async_reset_state_pairs': len(common_states),
                'internal_alias_excluded': ['row_offset_in_group'] if top == 'vec_requant' else [],
                'prepared_model_sha256': model_hashes, 'formal_log_sha256': sha(log)}

    def production_composition(profiles):
        # 父模块逐文件保持相同；已证明的无状态函数可在全部周期及任意容量下替换。
        top = ROOT/'rtl/npu/writeback/vec_requant.sv'
        dependencies = resolve([top], ROOT)
        unchanged = {}
        for source in dependencies:
            relative = str(source.relative_to(ROOT))
            hashes[relative] = sha(source)
            if relative in SOURCES.values():
                continue
            original = subprocess.check_output(['git', 'show', f'{revision}:{relative}'], cwd=ROOT)
            assert original == source.read_bytes(), relative
            unchanged[relative] = sha(source)
        folder = out/'production_composition'
        folder.mkdir(exist_ok=True)
        netlist = folder/'hierarchy.json'
        flags = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1', '-GBUS_WIDTH=64', '-GVLEN=16',
                 '-GMAX_IA_REUSE=32', '-GENABLE_S16=1', '-Gp_compute_lanes=2',
                 '-Gp_input_rows=512', '-Gp_parameter_output=0']
        script = folder/'hierarchy.ys'
        script.write_text('read_slang --keep-hierarchy --top vec_requant '+
                          shlex.join(flags+list(map(str, dependencies)))+
                          '\nproc\nwrite_json '+shlex.quote(str(netlist))+'\n')
        execute([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script],
                folder/'hierarchy.log')
        modules = json.loads(netlist.read_text())['modules']
        instances = []
        supported = {(row['kind'], row['width'], row['low_width'], row['synthesis'])
                     for row in profiles if row['passed']}

        def combinational(name, visited):
            if name in visited:
                return
            visited.add(name)
            for cell in modules[name].get('cells', {}).values():
                kind = cell['type']
                if kind in modules:
                    combinational(kind, visited)
                else:
                    assert not re.search(r'dff|latch|mem|anyseq|anyconst', kind), kind

        for name, module in modules.items():
            base = name.split('$', 1)[0]
            if base == 'requant_round_add':
                width = len(module['ports']['i_a']['bits'])
                low = len(module['netnames']['low_sum']['bits'])-1
                kind = 'round'
            elif base == 'requant_group_last':
                width = len(module['ports']['i_row']['bits'])
                low = 0
                kind = 'group'
            else:
                continue
            assert (kind, width, low, True) in supported
            combinational(name, set())
            instances.append({'instance': name, 'kind': kind, 'width': width,
                              'low_width': low, 'covered_by_unconstrained_helper_proof': True})
        assert len([x for x in instances if x['kind'] == 'round']) == 2
        assert len([x for x in instances if x['kind'] == 'group']) == 1
        result = {'passed': True, 'method': 'compositional_substitution', 'options': flags,
                  'unchanged_parent_and_dependency_sha256': unchanged,
                  'changed_combinational_helpers': SOURCES, 'instances': instances,
                  'external_inputs_constrained': False, 'all_public_cycle_behaviors_preserved': True,
                  'hierarchy_sha256': sha(netlist)}
        netlist.unlink()
        print('production_composition PASS', flush=True)
        return result

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        profiles = list(pool.map(helper, [(*row, synthesis) for row in PROFILES for synthesis in (False, True)]))
    parents = []
    if not args.skip_parent:
        jobs = [('requant_compute_lane', [f'-Gp_delayed_parameters={delayed}'], synthesis,
                 f'lane_delayed{delayed}_'+('synthesis' if synthesis else 'generic'))
                for delayed in (0, 1) for synthesis in (False, True)]
        jobs += [('vec_requant', ['-GBUS_WIDTH=64', '-GVLEN=4', '-GMAX_IA_REUSE=3',
                  '-GENABLE_S16=1', '-Gp_compute_lanes=2', '-Gp_input_rows=12', '-Gp_parameter_output=0'],
                  synthesis, 'vec_small_'+('synthesis' if synthesis else 'generic')) for synthesis in (False, True)]
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            parents = list(pool.map(parent, jobs))
    composition = production_composition(profiles)
    assert hashes == {name: sha(ROOT/name) for name in hashes}
    report = {'passed': True, 'reference_commit': revision, 'source_sha256': hashes,
              'profiles': profiles, 'parents': parents, 'production_composition': composition,
              'four_state_comparisons': sum(row['four_state_comparisons'] for row in profiles),
              'test_sha256': sha(Path(__file__))}
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'passed': True, 'helper_proofs': len(profiles), 'parent_proofs': len(parents),
                      'four_state_comparisons': report['four_state_comparisons']}), flush=True)


if __name__ == '__main__':
    main()
