#!/usr/bin/env python3
"""Compare all shared-memory outputs against a selected source revision."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/buffers/ia_ps_shared_ram.sv')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='aa2ef9a3')
    parser.add_argument('--out', type=Path, default=ROOT/'build/shared_equivalence')
    parser.add_argument('--cycles', type=int, default=50000)
    parser.add_argument('--fpga-primitives', action='store_true', help='Simulate the official LUT6/MUXF7/MUXF8 models')
    parser.add_argument('--profiles', nargs='+', default=['2048:6', '2048:7', '4096:8', '8192:6', '8192:7', '8192:9'])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = out/'ia_ps_shared_ram_ref.sv'
    original = subprocess.check_output(['git', 'show', f'{args.reference}:{SOURCE}'], cwd=ROOT, text=True)
    reference.write_text(original.replace('module ia_ps_shared_ram #(', 'module ia_ps_shared_ram_ref #(', 1))
    sources = [ROOT/SOURCE, ROOT/'rtl/common/REGFILE.v', Path(__file__).with_name('tb_equivalence.sv')]
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    primitive_hash = None
    primitive_sources = []
    if args.fpga_primitives:
        import pyosys
        library = Path(pyosys.__file__).parent/'share/xilinx/cells_sim.v'
        model = out/'xilinx_mux_models.sv'
        blocks = [re.search(r'^module ' + name + r'\b.*?^endmodule', library.read_text(),
                  re.MULTILINE | re.DOTALL).group(0) for name in ('LUT6', 'MUXF7', 'MUXF8')]
        model.write_text('\n\n'.join(re.sub(r'\bspecify\b.*?\bendspecify\b', '', block,
                         flags=re.DOTALL) for block in blocks) + '\n')
        primitive_hash = hashlib.sha256(model.read_bytes()).hexdigest()
        primitive_sources = ['-DSYNTHESIS', str(model)]
    reports = []
    for profile in args.profiles:
        bank_bytes, banks = map(int, profile.split(':'))
        folder = out/f'b{bank_bytes}_n{banks}'
        folder.mkdir(exist_ok=True)
        command = ['verilator', '--binary', '--timing', '-Wno-fatal', '-j', '1',
                   '--top-module', 'tb_shared_ram_equivalence', '--Mdir', str(folder/'obj'),
                   f'-GBANK_BYTES={bank_bytes}', f'-GBANK_COUNT={banks}', f'-GRANDOM_CYCLES={args.cycles}',
                   *map(str, sources), str(reference), *primitive_sources]
        with (folder/'compile.log').open('w') as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        binary = folder/'obj/Vtb_shared_ram_equivalence'
        result = subprocess.run([str(binary)], cwd=ROOT, text=True, capture_output=True)
        (folder/'run.log').write_text(result.stdout+result.stderr)
        if result.returncode or 'SHARED_EQ_PASS' not in result.stdout:
            raise RuntimeError(result.stdout+result.stderr)
        match = re.search(r'SHARED_EQ_PASS (.*)', result.stdout)
        counters = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', match.group(1))}
        reports.append(dict(bank_bytes=bank_bytes, banks=banks, passed=True, **counters))
        print(json.dumps(reports[-1]), flush=True)
    if hashes != {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}:
        raise RuntimeError('Sources changed during verification')
    (out/'summary.json').write_text(json.dumps(dict(passed=True, reference=args.reference,
        source_sha256=hashes, reference_sha256=hashlib.sha256(original.encode()).hexdigest(),
        compared_ports=7, fpga_primitives=args.fpga_primitives,
        primitive_model_sha256=primitive_hash, profiles=reports), indent=2)+'\n')


if __name__ == '__main__':
    main()
