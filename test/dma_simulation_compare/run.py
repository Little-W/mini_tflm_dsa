#!/usr/bin/env python3
"""验证线性 DMA 仿真比较器的四态文本一致性和综合状态等价。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/dma/axi_linear_block_dma.sv')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tokens(text: str) -> list[str]:
    text = re.sub(r'//[^\n]*|/\*.*?\*/', '', text, flags=re.S)
    return re.findall(r'\w+|[^\s\w]', text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    roots = {'reference': args.reference_root.resolve(), 'current': args.source_root.resolve()}
    hashes, prepared = {}, {}
    for label, root in roots.items():
        target = out / (label + '.sv')
        target.write_bytes((root / SOURCE).read_bytes())
        hashes[label], prepared[label] = digest(target), target
    report = dict(passed=False, source_sha256=hashes, preprocess=[], formal=[])
    for mode, defines in [('generic', []), ('fpga', ['XILINX_FPGA=1']),
                          ('asic', ['ASIC_SYNTHESIS=1', 'ASIC_SRAM=1'])]:
        outputs = {}
        for label, source in prepared.items():
            target = out / f'{label}_{mode}_preprocessed.sv'
            subprocess.run(['iverilog', '-g2012', '-E', *['-D'+value for value in defines],
                            '-o', str(target), str(source)], check=True)
            outputs[label] = target
        left, right = (tokens(outputs[label].read_text()) for label in roots)
        assert left == right, ('four-state statements changed', mode)
        assert 'u_rsp_last_equal' in left
        entry = dict(mode=mode, passed=True, identical_tokens=len(left),
                     preprocessed_sha256={label: digest(path) for label, path in outputs.items()})
        report['preprocess'].append(entry)
        print(json.dumps(entry), flush=True)
    synthesis = out / 'current_synthesis.sv'
    subprocess.run(['iverilog', '-g2012', '-E', '-DSYNTHESIS=1', '-DASIC_SYNTHESIS=1',
                    '-o', str(synthesis), str(prepared['current'])], check=True)
    assert 'u_rsp_last_equal' not in tokens(synthesis.read_text())
    for mode in ('asic', 'fpga'):
        folder = out / ('formal_' + mode)
        command = [sys.executable, str(ROOT / 'test/dma_byte_layout/run_formal.py'),
                   '--reference-rtl', str(prepared['reference']), '--rtl', str(prepared['current']),
                   '--production-parameters', '--context-parameters', '--'+mode,
                   '--out', str(folder)]
        with (out / (mode + '_formal.log')).open('w') as stream:
            subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
        summary = json.loads((folder / 'summary.json').read_text())
        assert summary['passed'] and all(item['passed'] for item in summary['runs'])
        entry = dict(mode=mode, passed=True, profiles=len(summary['runs']),
                     equivalent_bits=sum(item['equivalent_bits'] for item in summary['runs']),
                     summary_sha256=digest(folder / 'summary.json'))
        report['formal'].append(entry)
        print(json.dumps(entry), flush=True)
    assert all(digest(root / SOURCE) == hashes[label] for label, root in roots.items())
    report.update(passed=True, external_inputs_constrained=False,
                  four_state_scope='Complete non-SYNTHESIS module statements are identical',
                  synthesized_comparator_removed=True, checker_sha256=digest(Path(__file__)))
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
