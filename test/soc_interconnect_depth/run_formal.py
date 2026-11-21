#!/usr/bin/env python3
"""在不限制公开输入的条件下，证明互连全部状态与输出逐周期一致。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/soc/soc_axi_interconnect.sv')
REFERENCE = '2297cb12deac56b476f9a2a656da4038a9d8a75c'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def profiles():
    result = [dict(ADDR_WIDTH=32, DATA_WIDTH=width, CPU_MEM_DP=65536,
                   READ_OUTSTANDING=count, WRITE_OUTSTANDING=count)
              for width in (32, 64) for count in (1, 4)]
    result += [dict(ADDR_WIDTH=width, DATA_WIDTH=64, CPU_MEM_DP=capacity,
                    READ_OUTSTANDING=3, WRITE_OUTSTANDING=5,
                    CPU_RAM_BASE=base, NPU_AXIL_BASE=npu)
               for width, capacity, base, npu in
               [(40, 1031, 8195, 268435456), (64, 1, 0, 0),
                (32, 524288, -1048576, 268435456),
                (32, 1031, 33554432, 33554432)]]
    return result


def capacity_invariant(source, parameters):
    """在实际完整互连中检查计数与保存标志的无界状态关系。"""
    marker = '    output wire                         m_ctrl_rready\n);'
    if source.count(marker) != 1:
        raise ValueError('无法定位互连末尾端口')
    instrumented = source.replace(marker, marker.replace('\n);',
        ',\n    output wire formal_capacity_valid\n);'))
    relation = """    assign formal_capacity_valid =
        (cpu_arq_valid_q == (cpu_arq_count_q != 2'd0)) &&
        (ram_read_full_q == (ram_rd_outs_q == RD_OUTS_W'(RD_OUTS_DEPTH))) &&
        (ram_write_full_q == (ram_wr_outs_q == WR_OUTS_W'(WR_OUTS_DEPTH))) &&
        (cpu_arq_dest_flags_q[0] == {cpu_arq_dest_q[0] == D_ERR, cpu_arq_dest_q[0] == D_CTRL,
            cpu_arq_dest_q[0] == D_UART, cpu_arq_dest_q[0] == D_NPU, cpu_arq_dest_q[0] == D_RAM}) &&
        (cpu_arq_dest_flags_q[1] == {cpu_arq_dest_q[1] == D_ERR, cpu_arq_dest_q[1] == D_CTRL,
            cpu_arq_dest_q[1] == D_UART, cpu_arq_dest_q[1] == D_NPU, cpu_arq_dest_q[1] == D_RAM});
"""
    instrumented = instrumented.replace('    dest_e cpu_ar_dest;', relation + '    dest_e cpu_ar_dest;')
    header = source.split('\n);', 1)[0]
    ports = re.findall(r'^\s*(input|output)\s+(?:(?:wire|logic)\s+)*(\[[^\]]+\]\s*)?(\w+)\s*[,\n]',
                       header + '\n', re.M)
    inputs = [(width or '', name) for direction, width, name in ports if direction == 'input']
    constants = '\n'.join(f'    localparam {key}={value};' for key,value in parameters.items())
    declarations = ',\n'.join(f'    input logic {width}{name}' for width,name in inputs)
    arguments = ','.join(f'.{key}({key})' for key in parameters)
    connections = ','.join(f'.{name}({name})' for _,name in inputs)
    wrapper = f"""module capacity_invariant #(
    parameter ADDR_WIDTH={parameters['ADDR_WIDTH']}, DATA_WIDTH={parameters['DATA_WIDTH']}
)(
{declarations},
    output wire o_correct
);
{chr(10).join(line for line in constants.splitlines() if not re.search(r'localparam (ADDR_WIDTH|DATA_WIDTH)=',line))}
    soc_axi_interconnect #({arguments}) dut({connections},.formal_capacity_valid(o_correct));
endmodule
"""
    return instrumented + '\n' + wrapper


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default=REFERENCE)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current_source = (args.source_root / SOURCE).read_bytes()
    snapshots = {}
    for label in ('reference', 'current'):
        path = out / label / SOURCE.name
        path.parent.mkdir(exist_ok=True)
        content = (((args.reference_root / SOURCE).read_bytes() if args.reference_root else
                    subprocess.check_output(['git', 'show', f'{args.reference_ref}:{SOURCE}'], cwd=ROOT))
                   if label == 'reference' else (args.source_root / SOURCE).read_bytes())
        path.write_bytes(content)
        snapshots[label] = path
    report = dict(reference_ref=str(args.reference_root.resolve()) if args.reference_root else args.reference_ref,
                  source_root=str(args.source_root.resolve()), inputs_constrained=False,
                  scope='Every state element and public output, including arbitrary handshake combinations',
                  source_sha256={name: digest(path) for name, path in snapshots.items()},
                  rtl_source_sha256=hashlib.sha256(current_source).hexdigest(),
                  capacity_state_relation_compared=True,
                  invariant_runs=[], runs=[], passed=False)
    for index, parameters in enumerate(profiles()):
        name = 'case' + str(index)
        options = ' '.join(f'-G{key}={value}' for key, value in parameters.items())
        has_flags = 'logic ram_read_full_q, ram_write_full_q;' in current_source.decode()
        if has_flags:
            invariant = out / (name + '_capacity.sv')
            invariant.write_text(capacity_invariant(current_source.decode(), parameters))
            invariant_script, invariant_log = out / (name + '_capacity.ys'), out / (name + '_capacity.log')
            invariant_script.write_text(
                f'read_slang --top capacity_invariant {shlex.quote(str(invariant))}\n'
                'prep -top capacity_invariant -flatten\nasync2sync\nmemory_map\nopt -full\n'
                'sat -seq 2 -tempinduct -maxsteps 5 -set-at 1 rst_n 0 -prove o_correct 1 -verify\n')
            with invariant_log.open('w') as stream:
                subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                '--worker', str(invariant_script)], cwd=ROOT, stdout=stream,
                               stderr=subprocess.STDOUT, check=True, timeout=180)
            if 'Induction step proven: SUCCESS!' not in invariant_log.read_text():
                raise RuntimeError('容量状态关系未完成归纳证明')
            report['invariant_runs'].append(dict(case=name, passed=True,
                source_sha256=digest(invariant), log_sha256=digest(invariant_log)))
        commands = []
        for label, path in snapshots.items():
            observed = path
            if label == 'current' and has_flags:
                text = path.read_text()
                pattern = r'    // 容量标志[^\n]*\n    always_ff.*?(?=    always_ff)'
                replacement = """    assign cpu_arq_valid_q = cpu_arq_count_q != 2'd0;
    assign ram_read_full_q = ram_rd_outs_q == RD_OUTS_W'(RD_OUTS_DEPTH);
    assign ram_write_full_q = ram_wr_outs_q == WR_OUTS_W'(WR_OUTS_DEPTH);
    for(genvar entry=0;entry<2;entry++) begin : g_formal_dest_flags
        assign cpu_arq_dest_flags_q[entry] = {cpu_arq_dest_q[entry] == D_ERR,
            cpu_arq_dest_q[entry] == D_CTRL, cpu_arq_dest_q[entry] == D_UART,
            cpu_arq_dest_q[entry] == D_NPU, cpu_arq_dest_q[entry] == D_RAM};
    end
"""
                text,count = re.subn(pattern,replacement,text,count=1,flags=re.S)
                if count != 1:
                    raise ValueError('无法定位已证明的容量标志更新块')
                observed = out / 'current_observed.sv'
                observed.write_text(text)
            commands += [f'read_slang --top soc_axi_interconnect {options} {shlex.quote(str(observed))}',
                         'prep -top soc_axi_interconnect -flatten', 'memory_map', 'async2sync', 'opt_clean',
                         f'rename soc_axi_interconnect {label}', f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                     'opt_merge', 'equiv_simple -short -seq 1', 'opt_clean',
                     'equiv_induct -seq 2', 'equiv_status -assert']
        script, log = out / (name + '.ys'), out / (name + '.log')
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True, timeout=180)
        text = log.read_text()
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        if not match or int(match[2]) or 'Equivalence successfully proven' not in text:
            raise RuntimeError('Complete interconnect equivalence not established')
        row = dict(case=name, parameters=parameters, passed=True,
                   equivalent_bits=int(match[1]), log_sha256=digest(log))
        report['runs'].append(row)
        print(json.dumps(row), flush=True)
    if (args.source_root / SOURCE).read_bytes() != current_source:
        raise RuntimeError('Source changed during verification')
    report['passed'] = True
    report['equivalent_bits'] = sum(row['equivalent_bits'] for row in report['runs'])
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
