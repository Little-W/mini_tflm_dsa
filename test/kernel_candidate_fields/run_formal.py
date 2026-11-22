#!/usr/bin/env python3
"""证明候选字段比较、突发编码及完整加载器全部状态和公开输出等价。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_current_source, read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/rtl'))
from source_files import with_dependencies
SOURCE = Path('rtl/npu/loaders/kernel_loader.sv')
DEPENDENCIES = [Path('rtl/npu/loaders/kernel_loader_ctrl.sv'),
                Path('rtl/npu/loaders/kernel_loader_buffer.sv')]

EQUAL_PROOF = '''module kernel_equal_proof #(
    parameter int p_width=160
) (
    input logic [p_width-1:0] current_value,saved_value,
    output logic equivalent
);
    logic equal_result;
    kernel_candidate_equal #(.p_width(p_width)) dut (
        .i_current(current_value),.i_saved(saved_value),.o_equal(equal_result)
    );
    assign equivalent=equal_result==(current_value==saved_value);
endmodule
'''

BURST_PROOF = '''module kernel_burst_proof #(
    parameter int p_width=32, parameter int p_bus_width=64, parameter int p_size=16
) (
    input logic [p_width-1:0] columns,
    input logic use16,tile_packed,
    output logic equivalent
);
    localparam int p_s8=p_bus_width/8;
    localparam int p_s16=p_bus_width/16;
    logic [p_width-1:0] reference_beats;
    logic [7:0] result;
    always_comb begin
        if(tile_packed)reference_beats=p_width'(p_size/p_s8)<<(use16?1:0);
        else if(columns==0)reference_beats=p_width'(1);
        else if(use16)reference_beats=(columns+p_width'(p_s16-1))>>$clog2(p_s16);
        else reference_beats=(columns+p_width'(p_s8-1))>>$clog2(p_s8);
    end
    kernel_burst_encode #(.p_width(p_width),.p_bus_width(p_bus_width),.p_size(p_size)) dut (
        .i_columns(columns),.i_use16(use16),.i_tile_packed(tile_packed),.o_length_m1(result)
    );
    assign equivalent=result==8'(reference_beats-1);
endmodule
'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='7254ced6')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    common = sorted(p for p in (ROOT/'rtl/common').glob('*') if p.suffix in ('.v', '.sv'))
    sources = [ROOT/SOURCE] + [ROOT/p for p in DEPENDENCIES] + common
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in sources}
    current = out/'current.sv'
    reference = out/'reference.sv'
    current.write_text(read_current_source(ROOT / SOURCE))
    reference.write_bytes(read_rtl_source(f'{args.reference_rev}:{SOURCE}', cwd=ROOT))
    equal_proof = out/'equal_proof.sv'
    burst_proof = out/'burst_proof.sv'
    equal_proof.write_text(EQUAL_PROOF)
    burst_proof.write_text(BURST_PROOF)
    import pyosys
    library = Path(pyosys.__file__).parent/'share/xilinx/cells_sim.v'
    model = out/'lut6.sv'
    model_text = re.search(r'^module LUT6\b.*?^endmodule', library.read_text(), re.M|re.S)[0]
    model.write_text(re.sub(r'\bspecify\b.*?\bendspecify\b', '', model_text, flags=re.S)+'\n')
    report = {'passed': False, 'reference_rev': args.reference_rev, 'source_sha256': hashes,
              'source_input_constraints': False, 'equal_profiles': [], 'burst_profiles': [],
              'loader_profiles': [], 'primitive_model_sha256': digest(model)}

    def run(name, commands, expected):
        script = out/(name+'.ys')
        log = out/(name+'.log')
        script.write_text('\n'.join(commands)+'\n')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                                     '--worker', str(script)], cwd=ROOT, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=300)
        text = log.read_text()
        if result.returncode or expected not in text:
            raise RuntimeError(f'Formal comparison did not complete: {log}')
        return text, digest(log)

    for width in (1, 2, 3, 4, 5, 31, 32, 160, 320):
        for configuration in ('ASIC_SYNTHESIS', 'XILINX_FPGA'):
            commands = [f'read_slang -D {configuration}=1 --top kernel_equal_proof '
                        f'-Gp_width={width} '+
                        ' '.join(shlex.quote(str(p)) for p in (current, model, equal_proof)),
                        'prep -top kernel_equal_proof -flatten',
                        'sat -verify -prove equivalent 1 -show-inputs -show-outputs']
            _, log_hash = run(f'equal_w{width}_{configuration}', commands,
                              'SAT proof finished - no model found: SUCCESS!')
            report['equal_profiles'].append({'width': width, 'configuration': configuration, 'passed': True,
                                             'log_sha256': log_hash})
    for width, bus, size in ((8, 32, 4), (8, 64, 16), (10, 32, 4), (11, 64, 16),
                             (12, 128, 16), (16, 32, 4), (32, 32, 4), (32, 32, 16),
                             (32, 64, 16), (32, 128, 16), (64, 64, 16),
                             (32, 24, 16), (32, 48, 16), (32, 96, 16)):
        commands = [f'read_slang -D ASIC_SYNTHESIS=1 --top kernel_burst_proof '
                    f'-Gp_width={width} -Gp_bus_width={bus} -Gp_size={size} '+
                    ' '.join(shlex.quote(str(p)) for p in (current, burst_proof)),
                    'prep -top kernel_burst_proof -flatten',
                    'sat -verify -prove equivalent 1 -show-inputs -show-outputs']
        _, log_hash = run(f'burst_w{width}_b{bus}_s{size}', commands,
                          'SAT proof finished - no model found: SUCCESS!')
        report['burst_profiles'].append({'width': width, 'bus': bus, 'size': size,
                                         'passed': True, 'log_sha256': log_hash})
    print('All equality and burst encoding profiles passed', flush=True)
    for size, count, bus in ((4, 8, 32), (16, 16, 32), (16, 29, 64), (16, 29, 128)):
        commands = []
        for label, source in [('reference', reference), ('current', current)]:
            paths = with_dependencies([source] + sources[1:], ROOT)
            commands += [f'read_slang -D ASIC_SYNTHESIS=1 --top kernel_loader '
                         f'-GSIZE={size} -GCOUNT_WIDTH={count} -GBUS_WIDTH={bus} -GDATA_WIDTH=16 '+
                         ' '.join(shlex.quote(str(p)) for p in paths),
                         'prep -top kernel_loader -flatten', 'memory_map', 'async2sync', 'opt_clean',
                         f'rename kernel_loader {label}', f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                     'equiv_simple -seq 1', 'opt_clean', 'equiv_induct -seq 2', 'equiv_status -assert']
        text, log_hash = run(f'loader_s{size}_c{count}_b{bus}', commands,
                             'Equivalence successfully proven')
        count_match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        report['loader_profiles'].append({'size': size, 'count_width': count, 'bus_width': bus,
                                         'passed': True, 'equivalent_bits': int(count_match[1]),
                                         'log_sha256': log_hash})
        print(json.dumps(report['loader_profiles'][-1]), flush=True)
    if hashes != {str(p.relative_to(ROOT)): digest(p) for p in sources}:
        raise RuntimeError('Sources changed during verification')
    report['passed'] = True
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
