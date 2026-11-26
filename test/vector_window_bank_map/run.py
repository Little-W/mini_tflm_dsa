#!/usr/bin/env python3
"""穷举窗口分区选择的四态输入，并证明完整操作数存储模块等价。"""
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
REFERENCE = '4f0fbf93'
SOURCE = Path('rtl/npu/conv/vector_engine_operand_store.sv')
HELPERS = [Path('rtl/npu/conv/vector_window_bank_map.sv'),
           Path('rtl/npu/conv/vector_window_valid_mux.sv')]
PARAMETERS = {'p_tile': 16, 'p_bus_width': 64, 'p_dma_size': 64,
              'p_pe_count': 8, 'p_window_lanes': 8,
              'p_shared_quant_enable': 1, 'p_shared_storage_enable': 1}

BENCH = r'''`timescale 1ns/1ps
module tb;
    logic [5:0] stimulus;
    logic [2:0] first_value, first_expected;
    logic [7:0][2:0] source_value, source_expected;
    logic [3:0] valid_values;
    logic valid_value, valid_expected;
    integer value_index, bit_index, digits;

    vector_window_bank_map u_map (
        .i_base(stimulus[5:3]), .i_column(stimulus[2:0]),
        .o_first(first_value), .o_source(source_value)
    );
    vector_window_valid_mux u_valid (
        .i_values(stimulus[5:2]), .i_index(stimulus[1:0]), .o_value(valid_value)
    );
    assign first_expected = stimulus[5:3] + stimulus[2:0];
    for (genvar bank = 0; bank < 8; bank++) begin : g_expected
        assign source_expected[bank] = 3'(bank) - first_expected;
    end
    assign valid_values = stimulus[5:2];
    assign valid_expected = valid_values[stimulus[1:0]];

    initial begin
        for (value_index = 0; value_index < 4096; value_index++) begin
            digits = value_index;
            for (bit_index = 0; bit_index < 6; bit_index++) begin
                case (digits % 4)
                    0: stimulus[bit_index] = 1'b0;
                    1: stimulus[bit_index] = 1'b1;
                    2: stimulus[bit_index] = 1'bx;
                    3: stimulus[bit_index] = 1'bz;
                endcase
                digits = digits / 4;
            end
            #1;
            if ({first_value, source_value} !== {first_expected, source_expected})
                $fatal(1, "分区编号不一致：input=%b", stimulus);
            if (valid_value !== valid_expected)
                $fatal(1, "有效位不一致：input=%b", stimulus);
        end
        $display("PASS four_state_vector_comparisons=8192");
        $finish;
    end
endmodule
'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(['git', 'rev-parse', REFERENCE+'^{commit}'],
                                      cwd=ROOT, text=True).strip()
    reference = out/'reference.sv'
    reference.write_bytes(subprocess.check_output(
        ['git', 'show', f'{revision}:{SOURCE}'], cwd=ROOT))
    bench = out/'tb.sv'
    bench.write_text(BENCH)
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    hashes, jobs = {}, []
    for synthesis in (False, True):
        mode = 'synthesis' if synthesis else 'generic'
        commands = []
        for label, path in [('reference', reference), ('candidate', ROOT/SOURCE)]:
            dependencies = resolve([path], ROOT)
            hashes.update({str(p.relative_to(ROOT)): digest(p) for p in dependencies
                           if p.is_relative_to(ROOT) and not p.is_relative_to(out)})
            options = ['-I'+str(ROOT/'include')]
            if synthesis:
                options.append('-DSYNTHESIS=1')
            options += [f'-G{key}={value}' for key, value in PARAMETERS.items()]
            commands += ['read_slang --top vector_engine_operand_store '+
                         shlex.join(options+list(map(str, dependencies))),
                         'setattr -mod -unset keep_hierarchy',
                         'setattr -unset keep_hierarchy',
                         'prep -top vector_engine_operand_store -flatten',
                         'memory_map', 'async2sync', 'opt -full',
                         'rename -top '+label, 'design -stash '+label]
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from candidate -as candidate candidate',
                     'equiv_make reference candidate proof', 'hierarchy -top proof',
                     'equiv_simple -seq 2', 'opt_clean', 'equiv_induct -seq 3',
                     'equiv_status -assert']
        script = out/(mode+'.ys')
        script.write_text('\n'.join(commands)+'\n')
        jobs.append((mode, synthesis, script))

    def verify(job):
        mode, synthesis, script = job
        formal_log = out/(mode+'_formal.log')
        with formal_log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], cwd=ROOT, check=True,
                           stdout=stream, stderr=subprocess.STDOUT, timeout=600)
        assert 'Equivalence successfully proven' in formal_log.read_text()
        executable = out/(mode+'.vvp')
        compile_log = out/(mode+'_compile.log')
        command = ['iverilog', '-g2012', '-s', 'tb', '-o', str(executable)]
        if synthesis:
            command += ['-DSYNTHESIS=1']
        command += list(map(str, [ROOT/path for path in HELPERS]+[bench]))
        with compile_log.open('w') as stream:
            subprocess.run(command, check=True, stdout=stream, stderr=subprocess.STDOUT)
        run_log = out/(mode+'_four_state.log')
        with run_log.open('w') as stream:
            subprocess.run(['vvp', str(executable)], check=True,
                           stdout=stream, stderr=subprocess.STDOUT, timeout=120)
        assert 'PASS four_state_vector_comparisons=8192' in run_log.read_text()
        print(mode+' PASS', flush=True)
        return {'synthesis': synthesis, 'passed': True,
                'four_state_vector_comparisons': 8192,
                'formal_log_sha256': digest(formal_log),
                'four_state_log_sha256': digest(run_log)}

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(verify, jobs))
    assert hashes == {name: digest(ROOT/name) for name in hashes}
    report = {'passed': True, 'reference_commit': revision,
              'parameters': PARAMETERS, 'inputs_constrained': False,
              'all_public_outputs_compared': True,
              'source_sha256': hashes, 'test_sha256': digest(Path(__file__)),
              'four_state_vector_comparisons': 16384, 'profiles': results}
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
