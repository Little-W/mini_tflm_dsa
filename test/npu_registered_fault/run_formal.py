#!/usr/bin/env python3
"""从实际 NPU 提取配置接收逻辑，证明故障期间停止接收及握手一致性。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    extractor_path = ROOT / 'test/npu_admission/run_formal.py'
    spec = importlib.util.spec_from_file_location('admission_extract', extractor_path)
    extractor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(extractor)
    top_path = ROOT / 'rtl/npu/top/npu_top.sv'
    source = top_path.read_text()
    if not re.search(r'\.p_register_bus_error\s*\(\s*1\x27b1\s*\)', source):
        raise RuntimeError('The NPU must enable registered DMA error reporting')
    body = extractor.admission(source, 'admission_proof')
    body = body.replace('    output logic sa_ready, cfg_start_event);', '''
    input logic task_fault, kernel_loader_o_quiescent,
    input logic kernel_loader_o_admission_request, block_dma_arbiter_o_kernel_eligible,
    output logic sa_ready, cfg_start_event,
    output logic ready_correct, handshake_correct, fault_blocked);
    logic block_dma_arbiter_i_abort;
    assign block_dma_arbiter_i_abort = task_fault || abort_state != 2'd0;''')
    body = body.replace('\nendmodule\n', '''
    logic expected_kernel_idle, expected_ready;
    assign expected_kernel_idle = p_admission_use_lut ?
        kernel_loader_o_quiescent &&
        !(kernel_loader_o_admission_request && block_dma_arbiter_o_kernel_eligible) :
        kernel_prefetch_idle;
    assign expected_ready = !task_fault && abort_state == AB_IDLE &&
        !run_vector && !vector_rejected && vector_engine_ready && ctrl_sa_ready &&
        frame_scheduler_ready && !cfg_stage0_valid && !cfg_stage1_valid &&
        !cfg_stage2_valid && operand_cache_idle && ia_prefetch_idle && expected_kernel_idle;
    assign ready_correct = sa_ready == expected_ready;
    assign handshake_correct = cfg_start_event == (calc_start && sa_ready && !cfg_vector_enable);
    assign fault_blocked = !task_fault || (!sa_ready && !cfg_start_event);
endmodule
''')
    rtl = out / 'actual_admission.sv'
    rtl.write_text(body)
    proofs = []
    for label, defines in (('fpga', '-DSYNTHESIS=1 -DXILINX_FPGA=1'),
                           ('asic', '-DASIC_SYNTHESIS=1')):
        commands = [f'read_slang {defines} --top admission_proof {shlex.quote(str(rtl))}',
                    'prep -top admission_proof -flatten', 'check -assert',
                    'sat -verify -prove ready_correct 1 -prove handshake_correct 1 '
                    '-prove fault_blocked 1 -show-inputs -show-outputs']
        script, log = out / f'{label}.ys', out / f'{label}.log'
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, timeout=120, check=True)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise RuntimeError(f'Proof did not complete: {label}')
        proofs.append(dict(configuration=label, passed=True, log_sha256=digest(log)))
    report = dict(passed=True, inputs_constrained=False, proofs=proofs,
                  source_sha256={str(path.relative_to(ROOT)): digest(path)
                                 for path in (top_path, extractor_path, Path(__file__))},
                  extracted_rtl_sha256=digest(rtl))
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(passed=True, configurations=len(proofs))))


if __name__ == '__main__':
    main()
