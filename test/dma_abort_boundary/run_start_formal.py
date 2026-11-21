#!/usr/bin/env python3
"""证明 DMA 命令接收事件对所有请求方、授予编码和中止条件保持相同。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/dma/axi_block_dma_arbiter.sv')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--reference', default='dde5e7c9')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = (ROOT / SOURCE).read_text()
    reference = subprocess.check_output(['git', 'show', f'{args.reference}:{SOURCE}'], cwd=ROOT, text=True)
    assigns = []
    for name in ('dw_granted', 'ia_granted', 'kernel_granted', 'bias_granted', 'quant_granted'):
        assigns.append(re.search(r'    assign ' + name + r'\s*=.*?;', source, re.S)[0])
    for name in ('C_IA', 'C_KERNEL', 'C_BIAS', 'C_QUANT', 'C_DW'):
        assigns.append(re.search(r'    assign rd_client_accept\[' + name + r'\]\s*=.*?;', source, re.S)[0])
    assigns.append(re.search(r'    assign rd_dma_start\s*=.*?;', source, re.S)[0])
    choices = []
    for name in ('C_DW', 'C_IA', 'C_KERNEL', 'C_BIAS', 'C_QUANT'):
        match = re.search(r'\b' + name + r': begin\s*(?:if \(ENABLE_QUANT_CLIENT != 0\) begin\s*)?'
                          r'rd_dma_start\s*=\s*(.*?);', reference, re.S)
        if match is None:
            raise ValueError('找不到参考请求方的接收表达式：' + name)
        enable = 'ENABLE_QUANT_CLIENT != 0 && ' if name == 'C_QUANT' else ''
        choices.append(name + ': ref_start = ' + enable + '(' + match[1] + ');')
    typedef = re.search(r'    typedef enum logic \[2:0\].*?client_e;', source, re.S)[0]
    proof = out / 'proof.sv'
    proof.write_text('''module arbiter_start #(parameter int ENABLE_QUANT_CLIENT=1)(
        input logic [2:0] rd_command_client,
        input logic local_abort, rd_command_space,
        input logic dw_start, ia_start, kernel_start, bias_start, quant_start,
        output logic equivalent
    );
    ''' + typedef + '''
    logic dw_granted, ia_granted, kernel_granted, bias_granted, quant_granted, rd_dma_start, ref_start;
    logic [4:0] rd_client_accept;
    ''' + '\n'.join(assigns) + '''
    always_comb begin
        ref_start = 1'b0;
        case (rd_command_client)
    ''' + '\n'.join(choices) + '''
            default: ;
        endcase
    end
    assign equivalent = ref_start == rd_dma_start;
    endmodule
    ''')
    report = dict(passed=False, reference=args.reference, inputs_constrained=False, input_bits=10,
                  source_sha256=hashlib.sha256(source.encode()).hexdigest(),
                  reference_sha256=hashlib.sha256(reference.encode()).hexdigest(), runs=[])
    for enable in (0, 1):
        script, log = out / f'enable{enable}.ys', out / f'enable{enable}.log'
        script.write_text(f'read_slang --top arbiter_start -GENABLE_QUANT_CLIENT={enable} ' +
                          shlex.quote(str(proof)) + '\nprep -top arbiter_start -flatten\n'
                          'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py',
                                     '--worker', script], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        passed = result.returncode == 0 and 'SAT proof finished - no model found: SUCCESS' in log.read_text()
        report['runs'].append(dict(enable_quant_client=enable, passed=passed,
            log_sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
        if not passed:
            raise RuntimeError('DMA 命令接收比较未完成：' + str(log))
    if report['source_sha256'] != hashlib.sha256((ROOT / SOURCE).read_bytes()).hexdigest():
        raise RuntimeError('验证期间源码发生变化')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
