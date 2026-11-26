#!/usr/bin/env python3
"""证明窗口准备字段与当前存储项的关系及完整队列逐周期等价。"""
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
REFERENCE = '8a31b855'
SOURCE = Path('rtl/npu/dma/conv_window_queue.sv')
PROFILES = [(2, 4, 1), (3, 8, 2), (4, 8, 3), (7, 16, 4)]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def instrument(source, candidate):
    pattern = r'(\binput\s+wire\s+logic\s+frontend_rsp_last\b.*?)\);'
    source, count = re.subn(pattern, r'\1, output logic proof_invariant);',
                            source, count=1, flags=re.S)
    assert count == 1
    properties = runpy.run_path(str(ROOT/'test/window_queue/run_formal.py'))['PROPERTIES']
    properties = properties.replace('proof_invariant=', 'proof_structure=')
    array, port = ('descriptor_read_data', 1) if candidate else ('descriptor_o_rd_data', 0)
    current = '{'+','.join(f'{array}[{field}][{port}]' for field in (2, 1, 0))+'}'
    checks = f'''
  logic proof_structure, proof_value_relation;
{properties}
  assign proof_value_relation = failed || launch || !descriptor_available ||
      descriptor_prepared_data == {current};
  assign proof_invariant = proof_structure && (!observed_reset || proof_value_relation);
  // 独立归纳证明不导入 assume；完整等价随后使用已经证明的可达状态关系。
  always_comb assume(proof_value_relation);
'''
    return source.replace('endmodule', checks+'endmodule', 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(['git', 'rev-parse', REFERENCE+'^{commit}'],
                                      cwd=ROOT, text=True).strip()
    reference = subprocess.check_output(['git', 'show', f'{revision}:{SOURCE}'],
                                       cwd=ROOT, text=True)
    originals = {'reference': reference, 'candidate': (ROOT/SOURCE).read_text()}
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    dependencies, hashes = {}, {}
    for label, source in originals.items():
        snapshot = out/(label+'.sv')
        snapshot.write_text(instrument(source, label == 'candidate'))
        dependencies[label] = resolve([snapshot], ROOT)
        hashes.update({str(path.relative_to(ROOT)): digest(path)
                       for path in dependencies[label]
                       if path.is_relative_to(ROOT) and not path.is_relative_to(out)})
    hashes[str(SOURCE)] = digest(ROOT/SOURCE)
    hashes['test/window_queue/run_formal.py'] = digest(ROOT/'test/window_queue/run_formal.py')
    excluded = ['descriptor_i_rd_addr', 'descriptor_i_rd_en']
    excluded += [f'g_descriptor[{field}].u_value.{signal}'
                 for field in range(3)
                 for signal in ('i_rd_addr', 'i_rd_en', 'o_rd_data', 'read_accept')]
    blacklist = out/'read_port_signals.txt'
    blacklist.write_text('\n'.join(excluded)+'\n')

    def prove(job):
        depth, lanes, outstanding, synthesis = job
        name = f'd{depth}_l{lanes}_p{outstanding}_'+('synthesis' if synthesis else 'generic')
        options = [f'-GDEPTH={depth}', f'-GWINDOW_LANES={lanes}',
                   f'-Gp_frontend_outstanding={outstanding}']
        if synthesis:
            options.append('-DSYNTHESIS=1')
        commands = []
        for label in ('reference', 'candidate'):
            commands += ['read_slang --top conv_window_queue '+
                         shlex.join(options+list(map(str, dependencies[label]))),
                         'setattr -mod -unset keep_hierarchy', 'setattr -unset keep_hierarchy',
                         'prep -top conv_window_queue -flatten', 'memory_map', 'async2sync', 'opt -full',
                         'sat -verify -seq 2 -tempinduct -set-at 1 rst_n 0 '
                         '-prove proof_invariant 1 -maxsteps 10',
                         'rename -top '+label, 'design -stash '+label]
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from candidate -as candidate candidate',
                     'equiv_make -blacklist '+shlex.quote(str(blacklist))+' reference candidate proof',
                     'hierarchy -top proof', 'equiv_simple -seq 2 -set-assumes',
                     'opt_clean', 'equiv_induct -seq 3 -set-assumes', 'equiv_status -assert']
        script, log = out/(name+'.ys'), out/(name+'.log')
        script.write_text('\n'.join(commands)+'\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], cwd=ROOT, check=True,
                           stdout=stream, stderr=subprocess.STDOUT, timeout=600)
        content = log.read_text()
        assert content.count('Induction step proven: SUCCESS!') == 2
        assert 'Equivalence successfully proven!' in content
        match = re.findall(r'Of those cells (\d+) are proven and (\d+) are unproven', content)[-1]
        assert int(match[1]) == 0
        print(name+' PASS', flush=True)
        return {'depth': depth, 'lanes': lanes, 'outstanding': outstanding,
                'synthesis': synthesis, 'passed': True, 'proven_equivalent_nodes': int(match[0]),
                'independent_invariant_proofs': 2, 'log_sha256': digest(log)}

    jobs = [(*profile, synthesis) for profile in PROFILES for synthesis in (False, True)]
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(prove, jobs))
    assert hashes == {name: digest(ROOT/name) for name in hashes}
    report = {'passed': True, 'reference_commit': revision, 'source_sha256': hashes,
              'test_sha256': digest(Path(__file__)), 'all_public_outputs_compared': True,
              'external_inputs_constrained': False,
              'independent_invariant_reset': 'rst_n=0 at first sampled edge',
              'equivalence_state_relation': 'failed || launch || !descriptor_available || '
                  'descriptor_prepared_data equals current storage entry',
              'state_relation_proven_independently': True,
              'unmatched_read_port_signals': excluded, 'profiles': results}
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
