#!/usr/bin/env python3
"""验证线性 DMA 的突发算术与完整写状态机。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source

SOURCE = 'rtl/npu/dma/axi_linear_block_dma.sv'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(folder, commands):
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / 'run.ys'
    log = folder / 'formal.log'
    script.write_text('\n'.join(commands) + '\n')
    with log.open('w') as stream:
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                 '--worker', str(script)], stdout=stream,
                                stderr=subprocess.STDOUT, cwd=ROOT)
    text = log.read_text()
    if result.returncode:
        raise RuntimeError(text[-9000:])
    return text, sha(log)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rtl', type=Path, default=ROOT / SOURCE)
    parser.add_argument('--reference-ref', default='dba30863fce7a6c42d6e863ceafebf2023110d97')
    parser.add_argument('--reference-rtl', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = args.rtl.resolve()
    original = (args.reference_rtl.resolve().read_text() if args.reference_rtl else
                read_rtl_source(args.reference_ref + ':' + SOURCE, cwd=ROOT, text=True))
    candidate_text = current.read_text()
    observed_reference = original.replace('    logic [7:0] wr_cfg_burst_len_m1;',
        "    logic [7:0] wr_cfg_burst_len_m1;\n"
        "    (* keep *) wire [BEAT_CNT_W-1:0] wr_cfg_cross_last =\n"
        "        beat_count_t'(wr_cfg_burst_len_m1) + beat_count_t'(1);")
    if observed_reference == original:
        raise RuntimeError('Reference write configuration is missing')
    reference = out / 'reference.sv'
    candidate = out / 'candidate.sv'
    reference.write_text(observed_reference)
    candidate.write_text(candidate_text)
    common = [ROOT / 'rtl/common/regfile.v', ROOT / 'rtl/common/add_equal.sv']
    snapshots = []
    for path in common:
        target = out / path.name
        target.write_bytes(path.read_bytes())
        snapshots.append(target)
    wrapper = out / 'write_top.sv'
    wrapper_text = (ROOT / 'test/linear_dma_write_4k/linear_dma_write_4k_top.sv').read_text()
    wrapper_text = wrapper_text.replace('    input logic clk, rst_n,',
                                         '    input logic clk, rst_n, abort,')
    wrapper_text = wrapper_text.replace('        .clk, .rst_n,', '        .clk, .rst_n, .abort,')
    wrapper.write_text(wrapper_text)
    dependencies = [current, *common, Path(__file__).resolve(),
                    ROOT / 'test/linear_dma_write_4k/linear_dma_write_4k_top.sv']
    hashes = {str(path): sha(path) for path in dependencies}
    summary = {'passed': False, 'source_sha256': hashes,
               'reference_ref': None if args.reference_rtl else args.reference_ref,
               'reference_file': str(args.reference_rtl.resolve()) if args.reference_rtl else None,
               'original_reference_sha256': hashlib.sha256(original.encode()).hexdigest(),
               'reference_state_observation': 'Existing write burst length plus one, without state updates',
               'write_inputs_constrained': False, 'write_profiles': [], 'read_arithmetic_profiles': []}
    for size, slots, bus, outstanding, maximum in (
            (16, 4, 32, 4, 1024), (16, 4, 32, 1, 32), (16, 4, 64, 4, 2048),
            (16, 4, 128, 4, 4096), (64, 64, 64, 4, 2048), (64, 64, 64, 1, 8)):
        commands = []
        options = (f'-GSIZE={size} -GCACHE_BLOCKS={slots} -GBUS_WIDTH={bus} '
                   f'-GWRITE_OUTSTANDING={outstanding} -GDMA_MAX_BYTES={maximum}')
        for name, source in [('reference', reference), ('candidate', candidate)]:
            paths = ' '.join(shlex.quote(str(path)) for path in [source, wrapper, *snapshots])
            commands.extend([f'read_slang --top linear_dma_write_4k_top -D SYNTHESIS=1 '
                             f'-D XILINX_FPGA=1 {options} {paths}',
                             'prep -top linear_dma_write_4k_top -flatten', 'memory_map', 'async2sync',
                             'opt_clean', f'rename linear_dma_write_4k_top {name}', f'design -stash {name}'])
        commands.extend(['design -copy-from reference -as reference reference',
                         'design -copy-from candidate -as candidate candidate',
                         'equiv_make reference candidate equivalent', 'hierarchy -top equivalent',
                         'equiv_simple -seq 1', 'opt_clean', 'equiv_induct -seq 4', 'equiv_status -assert'])
        text, digest = execute(out / f'write_s{size}_k{slots}_b{bus}_o{outstanding}_m{maximum}', commands)
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        if 'Equivalence successfully proven' not in text or match is None:
            raise RuntimeError(text[-5000:])
        result = dict(size=size, cache_blocks=slots, bus_width=bus, outstanding=outstanding,
                      dma_max_bytes=maximum, passed=True, equivalent_bits=int(match[1]), log_sha256=digest)
        summary['write_profiles'].append(result)
        print(json.dumps(result), flush=True)

    begin = candidate_text.index('    assign rd_plan_page_beats =')
    end = candidate_text.index('    assign rd_cmd_start_addr_sum =', begin)
    actual_arithmetic = candidate_text[begin:end]
    for address_width, bus, maximum in ((16, 32, 1024), (17, 1024, 32768),
                                      (32, 32, 1024), (32, 64, 2048),
                                      (32, 64, 8), (32, 64, 256),
                                      (32, 128, 4096), (40, 64, 2048)):
        model = out / f'read_a{address_width}_b{bus}_m{maximum}.sv'
        model.write_text(f'''module read_arithmetic(
    input logic [{address_width-1}:0] address,
    input logic [8:0] remaining,
    output logic o_equiv
);
    localparam int REG_WIDTH = {address_width};
    localparam int ADDR_LSB = $clog2({bus}/8);
    localparam int MAX_BURST_BEATS = {maximum}/({bus}/8);
    typedef logic [8:0] beat_count_t;
    logic [REG_WIDTH-1:0] rd_plan_addr;
    beat_count_t rd_plan_remaining, rd_plan_selected, rd_plan_limited;
    logic [12:0] rd_plan_page_beats;
    logic rd_plan_page_limited, rd_plan_burst_limited;
    logic [REG_WIDTH:0] rd_plan_next_addr_sum;
    logic [12:0] expected_page;
    beat_count_t expected_limit, expected_selected;
    logic [REG_WIDTH-1:0] expected_next;
    // 物理 AXI 地址由实际选择阶段清除总线字内的偏移位。
    assign rd_plan_addr = {{address[REG_WIDTH-1:ADDR_LSB], {{ADDR_LSB{{1'b0}}}}}};
    assign rd_plan_remaining = remaining;
    assign rd_plan_selected = rd_plan_limited;
{actual_arithmetic}
    assign expected_page = (13'd4096 - {{1'b0, rd_plan_addr[11:0]}}) >> ADDR_LSB;
    assign expected_limit = remaining > beat_count_t'(MAX_BURST_BEATS) ?
        beat_count_t'(MAX_BURST_BEATS) : remaining;
    assign expected_selected = expected_page < 13'(expected_limit) ?
        beat_count_t'(expected_page) : expected_limit;
    assign expected_next = rd_plan_addr + (REG_WIDTH'(expected_selected) << ADDR_LSB);
    assign o_equiv = rd_plan_selected == expected_selected &&
        rd_plan_next_addr_sum[REG_WIDTH-1:0] == expected_next &&
        (remaining-rd_plan_selected) == (remaining-expected_selected) &&
        8'(rd_plan_selected-beat_count_t'(1)) == 8'(expected_selected-beat_count_t'(1));
endmodule
''')
        text, digest = execute(out / f'read_a{address_width}_b{bus}_m{maximum}',
            [f'read_slang --top read_arithmetic {shlex.quote(str(model))}',
             'prep -top read_arithmetic -flatten', 'sat -verify -prove o_equiv 1 -show-inputs'])
        if 'SUCCESS!' not in text:
            raise RuntimeError(text[-5000:])
        result = dict(address_width=address_width, bus_width=bus, dma_max_bytes=maximum,
                      passed=True, log_sha256=digest, model_sha256=sha(model))
        summary['read_arithmetic_profiles'].append(result)
        print(json.dumps(result), flush=True)
    if hashes != {str(path): sha(path) for path in dependencies}:
        raise RuntimeError('Sources changed during verification')
    summary['passed'] = True
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
