#!/usr/bin/env python3
"""Execute DMA parameter limits and alternative-core propagation checks."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import subprocess


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[2],
                        help='Source repository to validate (default: this repository)')
    parser.add_argument('--out', type=Path, required=True,
                        help='Directory for generated tests, binaries, logs, and summary.json')
    parser.add_argument('--verilator', default=os.environ.get('VERILATOR', 'verilator'),
                        help='Verilator executable (default: VERILATOR environment variable or PATH)')
    args = parser.parse_args()
    repo, out = args.repo.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    spec = importlib.util.spec_from_file_location('configuration_build_sim', repo/'test/model_benchmark/build_sim.py')
    build_sim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_sim)
    rejected_python = []
    for bus_width in (32,64):
        for value in (0,12,512,256*(bus_width//8)*2):
            try:
                build_sim.build_sim(out/f'python_w{bus_width}_{value}',
                                    bus_width=bus_width,dma_max_bytes=value)
            except ValueError:
                rejected_python.append(dict(bus_width=bus_width,dma_max_bytes=value))
            else:
                raise RuntimeError('Benchmark accepted an unsupported DMA length')
    main_cpp = out/'main.cpp'
    main_cpp.write_text('#include "Vparameter_test.h"\n#include "verilated.h"\n#include <cstdio>\nint main(int argc,char**argv){Verilated::commandArgs(argc,argv);Vparameter_test top;top.eval();if(!top.passed)return 2;std::puts("CONFIGURATION_BOUNDS_PASS");return 0;}\n')
    all_sources = {repo/'test/model_benchmark/build_sim.py'}
    all_sources.update((repo/'rtl/npu/gempact').glob('*.svh'))
    records = []
    def execute(name, sv, source_args, expected_accept=True, defines=()):
        directory = out/name
        directory.mkdir(parents=True, exist_ok=True)
        tb = directory/'parameter_test.sv'
        tb.write_text(sv)
        command = [args.verilator, '--cc', '--exe', '--assert', '-Wno-fatal',
                   '--top-module', 'parameter_test', '--Mdir', str(directory/'obj'),
                   '--output-groups', '0', '--output-split', '12000',
                   '-CFLAGS', '-std=c++17', *defines, *source_args, str(tb), str(main_cpp)]
        compile_command = ['make', '-C', str(directory/'obj'), '-f', 'Vparameter_test.mk', '-j', '1',
                           'OPT_FAST=-O0', 'OPT_SLOW=-O0', 'OPT_GLOBAL=-O0',
                           'VK_PCH_I_FAST=', 'VK_PCH_I_SLOW=', 'CFG_CXXFLAGS_PCH=-E']
        for cmd, filename in ((command, 'generate.log'), (compile_command, 'compile.log')):
            with (directory/filename).open('w') as stream:
                result = subprocess.run(cmd, cwd=repo, stdout=stream, stderr=subprocess.STDOUT, timeout=300)
            if result.returncode:
                raise RuntimeError(f'{name}: {filename}: '+(directory/filename).read_text()[-6000:])
        result = subprocess.run([str(directory/'obj/Vparameter_test')], cwd=repo,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
        (directory/'run.log').write_text(result.stdout)
        accepted = result.returncode == 0 and 'CONFIGURATION_BOUNDS_PASS' in result.stdout
        passed = accepted if expected_accept else result.returncode != 0 and 'DMA_MAX_BYTES' in result.stdout
        if not passed:
            raise RuntimeError(f'{name}: unexpected configuration result: {result.stdout}')
        record = {'name': name, 'passed': True, 'expected_accept': expected_accept,
                  'accepted': accepted, 'returncode': result.returncode,
                  'generate_command': command, 'compile_command': compile_command,
                  'testbench_sha256': digest(tb), 'binary_sha256': digest(directory/'obj/Vparameter_test')}
        records.append(record)
        print(json.dumps({key: record[key] for key in ('name', 'passed', 'accepted')}), flush=True)
    base_sources = [str(repo/name) for name in ('rtl/npu/dma/axi_linear_block_dma.sv',
                    'rtl/npu/conv/conv_axi_span_reader.sv', 'rtl/npu/gempact/gempact_panel_cache.sv')]
    all_sources.update(Path(path) for path in base_sources)
    supported_by_bus = {32:[4,8,16,32,64,128,256,512,1024],
                        64:[8,16,32,64,128,256,512,1024,2048]}
    for bus_width, supported in supported_by_bus.items():
      for name, values, accepted in (('supported_values', supported, True),
                                    ('reject_zero', (0,), False), ('reject_non_power_of_two', (12,), False),
                                    ('reject_over_limit', (supported[-1]*2,), False)):
        values_literal = ','.join(map(str, values))
        panel_instance = ('gempact_panel_cache #(.MAX_R(1),.MAX_W(1),.DMA_MAX_BYTES(LIMITS[i])) '
                          "panel_cache(.clk(1'b0),.rst_n(1'b0));") if bus_width==32 else ''
        sv = f'''module parameter_test(output logic passed);
localparam int LIMITS[{len(values)}]='{{{values_literal}}};
for(genvar i=0;i<{len(values)};i++)begin:g
 axi_linear_block_dma #(.BUS_WIDTH({bus_width}),.DMA_MAX_BYTES(LIMITS[i])) linear_dma(.clk(1'b0),.rst_n(1'b0));
 conv_axi_span_reader #(.BUS_WIDTH({bus_width}),.DMA_MAX_BYTES(LIMITS[i])) span_reader(.clk(1'b0),.rst_n(1'b0));
 {panel_instance}
end
initial passed=1;
endmodule
'''
        execute(f'axi{bus_width}_'+name, sv, base_sources, accepted)
    sources, source_args = build_sim.filelist_sources(repo/'veri/flist/dut_axil.f', repo/'veri/sim', repo/'picorv32')
    all_sources.update(sources)
    for core in ('panel', 'resident'):
        scope = 'dut.u_panel.u_writer.u_linear' if core == 'panel' else 'dut.u_resident.u_dma.u_linear'
        extra = '''assert(dut.u_panel.DMA_MAX_BYTES==16);
assert(dut.u_panel.u_writer.DMA_MAX_BYTES==16);
assert(dut.u_panel.u_cache.DMA_MAX_BYTES==16);
assert(dut.u_panel.u_cache.burst_for(32'h1000,7'd64)==3);
assert(dut.u_panel.u_cache.burst_for(32'h1ffc,7'd64)==0);''' if core == 'panel' else '''assert(dut.u_resident.DMA_MAX_BYTES==16);
assert(dut.u_resident.u_dma.DMA_MAX_BYTES==16);'''
        sv = f'''module parameter_test(output logic passed);
npu_top #(.DMA_MAX_BYTES(16)) dut(.clk(1'b0),.rst_n(1'b0));
initial begin
{extra}
assert({scope}.DMA_MAX_BYTES==16);
assert({scope}.read_segment_beats(32'h1000,9'd256)==4);
assert({scope}.write_segment_beats(32'h1000,9'd256)==4);
assert({scope}.read_segment_beats(32'h1ffc,9'd256)==1);
assert({scope}.write_segment_beats(32'h1ffc,9'd256)==1);
passed=1;
end
endmodule
'''
        execute(core+'_propagation', sv, source_args, defines=(
                '-DGEMPACT_'+core.upper()+'_ENGINE', '-DGEMMORA_PS_POOL_BYTES=500736'))
    report = {'passed': True, 'repository': str(repo), 'script_sha256': digest(__file__),
              'supported_dma_bytes_by_bus_width': supported_by_bus,
              'benchmark_rejected_dma_bytes': rejected_python,
              'checks': 'Parameter admission, hierarchy propagation, and actual RTL segment helper functions',
              'source_sha256': {str(Path(path).relative_to(repo)): digest(path) for path in sorted(all_sources)},
              'runs': records}
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
