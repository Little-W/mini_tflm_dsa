#!/usr/bin/env python3
"""检查量化移位的逐周期数值、暂停行为和四态传播。"""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = '548bda54'
SHIFT = 'rtl/npu/writeback/requant_shift_pipeline.sv'
LANE = 'rtl/npu/writeback/requant_compute_lane.sv'
VECTOR = 'rtl/npu/writeback/vec_requant.sv'
MODES = [('generic', []), ('synthesis', ['-DSYNTHESIS=1']),
         ('fpga', ['-DXILINX_FPGA=1']),
         ('fpga_synthesis', ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'])]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command, log):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(['git', 'rev-parse', REFERENCE+'^{commit}'], cwd=ROOT, text=True).strip()
    original = subprocess.check_output(['git', 'show', revision+':'+SHIFT], cwd=ROOT, text=True)
    reference = out/'reference.sv'
    reference.write_text(original)
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    dependencies = resolve([ROOT/VECTOR], ROOT)
    hashes = {str(path.relative_to(ROOT)): sha(path) for path in dependencies}

    def formal(job):
        mode, flags, kind, delayed = job
        key = mode+'_'+kind+'_delayed'+str(delayed)
        top = 'requant_shift_pipeline' if kind == 'shift' else 'requant_compute_lane'
        options = [] if kind == 'shift' else [f'-Gp_delayed_parameters={delayed}']
        formal_flags = flags if '-DSYNTHESIS=1' in flags else ['-USYNTHESIS', *flags]
        commands = []
        for label in ('reference', 'candidate'):
            sources = ([reference] if label == 'reference' else [])
            if kind == 'lane':
                sources.append(ROOT/LANE)
            elif label == 'candidate':
                sources.append(ROOT/SHIFT)
            files = resolve(sources, ROOT)
            commands += ['read_slang --top '+top+' '+shlex.join([*formal_flags, *options, *map(str, files)]),
                'setattr -mod -unset keep_hierarchy', 'setattr -unset keep_hierarchy',
                'prep -top '+top+' -flatten', 'memory_map', 'async2sync', 'opt -full',
                'rename -top '+label, 'design -stash '+label]
        private = out/(key+'_private_signals.txt')
        prefix = '' if kind == 'shift' else 'u_shift.'
        # 溢出只使用所需高位，未被输出使用的移位中间位不作为状态比较点。
        private.write_text(prefix+'coarse_value\n'+prefix+'fine_value\n')
        commands += ['design -copy-from reference -as reference reference',
            'design -copy-from candidate -as candidate candidate',
            'equiv_make -blacklist '+shlex.quote(str(private))+' reference candidate proof', 'hierarchy -top proof',
            'equiv_simple -short -seq 2', 'opt_clean', 'equiv_induct -seq 3', 'equiv_status -assert']
        script, log = out/(key+'.ys'), out/(key+'.log')
        script.write_text('\n'.join(commands)+'\n')
        execute([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
        assert 'Equivalence successfully proven!' in log.read_text()
        print(key+' PASS', flush=True)
        return {'mode': mode, 'top': top, 'delayed_parameters': delayed,
                'passed': True, 'all_public_outputs_compared': True,
                'external_inputs_constrained': False, 'formal_flags': formal_flags, 'log_sha256': sha(log)}

    simulation_reference = out/'simulation_reference.sv'
    simulation_reference.write_text(original.replace('module requant_shift_pipeline (', 'module reference (', 1))
    bench = out/'tb.sv'
    bench.write_text('''module tb;
reg clk=0,i_en=1;reg signed[63:0]i_product;reg[6:0]i_amount;
wire[34:0]expected,actual;integer checks=0;
reference ref_dut(.*,.o_quotient(expected[34:1]),.o_increment(expected[0]));
requant_shift_pipeline dut(.*,.o_quotient(actual[34:1]),.o_increment(actual[0]));
function automatic reg symbol(input integer value);
case(value%4)0:symbol=0;1:symbol=1;2:symbol=1'bx;default:symbol=1'bz;endcase
endfunction
task check;begin
if(actual!==expected)$fatal(1,"量化移位结果不同 sample=%0d",checks);checks++;
end endtask
initial begin
for(integer sample=0;sample<131072;sample++)begin
 i_en=sample%32<24 ? 1'b1 : symbol(sample>>3);
 i_amount=7'(sample>>4);i_product={$urandom,$urandom};
 case(sample%16)
 0:i_product=0;
 1:i_product=-1;
 2:i_product=64'h7fffffffffffffff;
 3:i_product=64'h8000000000000000;
 4:i_product=64'd1<<((sample>>8)%64);
 5:i_product=-(64'd1<<((sample>>8)%64));
 6:i_product[(sample>>8)%64]=1'bx;
 7:i_product[(sample>>8)%64]=1'bz;
 8:i_amount[(sample>>8)%7]=1'bx;
 9:i_amount[(sample>>8)%7]=1'bz;
 10:begin i_product='x;i_amount='z;end
 11:begin i_product=0;i_product[63]=1'bx;end
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
        simulation = out/(label+'_simulation')
        execute(['iverilog', '-g2012', *flags, '-s', 'tb', '-o', simulation,
                 simulation_reference, ROOT/SHIFT, bench], out/(label+'_compile.log'))
        log = out/(label+'_four_state.log')
        execute(['vvp', simulation], log)
        assert 'PASS comparisons=262144' in log.read_text()
        return {'mode': label, 'passed': True, 'comparisons': 262144, 'log_sha256': sha(log)}

    jobs = [(label, flags, kind, delayed) for label, flags in MODES
            for kind, delayed in [('shift', 0), ('lane', 0), ('lane', 1)]]
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        proofs = list(pool.map(formal, jobs))
        four = list(pool.map(four_state, MODES))
    unchanged = {}
    for source in dependencies:
        relative = str(source.relative_to(ROOT))
        if relative == SHIFT:
            continue
        assert subprocess.check_output(['git', 'show', revision+':'+relative], cwd=ROOT) == source.read_bytes(), relative
        unchanged[relative] = sha(source)
    assert hashes == {name: sha(ROOT/name) for name in hashes}
    report = {'passed': True, 'reference_commit': revision, 'formal': proofs,
              'four_state': four, 'four_state_comparisons': sum(x['comparisons'] for x in four),
              'source_sha256': hashes, 'test_sha256': sha(Path(__file__)),
              'production_composition': {'passed': True, 'method': 'complete_lane_interface_equivalence',
                  'all_parent_and_other_dependency_sources_unchanged': True,
                  'unchanged_dependency_sha256': unchanged,
                  'delayed_parameters_proven': [0, 1],
                  'all_external_inputs_unconstrained': True,
                  'all_public_cycle_behaviors_preserved': True}}
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'passed': True, 'formal_proofs': len(proofs),
                      'four_state_comparisons': report['four_state_comparisons']}), flush=True)

if __name__ == '__main__':
    main()
