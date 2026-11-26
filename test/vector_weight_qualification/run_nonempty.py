#!/usr/bin/env python3
"""证明完整操作数存储模块发布的权重写请求至少包含一个有效字节。"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/conv/vector_engine_operand_store.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    args = parser.parse_args()
    source_root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = source_root/SOURCE
    text = source.read_text().replace('module vector_engine_operand_store #(',
                                     'module weight_nonempty_property #(', 1)
    assert text.count('endmodule') == 1
    text = text.replace('endmodule', '''
  // 观察到复位后，所有实际发布的权重写请求必须包含至少一个有效字节。
  logic proof_reset_seen = 1'b0;
  always_ff @(posedge clk) begin
    if (!rst_n) proof_reset_seen <= 1'b1;
  end
  (* keep = 1 *) wire proof_nonempty = !proof_reset_seen ||
      !o_weight_write_en || (|o_weight_write_mask);
endmodule''')
    model = out/'property.sv'
    model.write_text(text)
    reader = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))
    dependencies = reader['with_dependencies']([model], source_root)
    hashes = {str(path.relative_to(source_root)): digest(path)
              for path in dependencies if path.is_relative_to(source_root) and path != model}
    hashes[str(SOURCE)] = digest(source)
    results = []
    for synthesis in (False, True):
        key = 'synthesis' if synthesis else 'generic'
        options = ['-Gp_tile=16', '-Gp_bus_width=64', '-Gp_dma_size=64',
                   '-Gp_pe_count=8', '-Gp_window_lanes=8',
                   '-Gp_shared_quant_enable=1', '-Gp_shared_storage_enable=1']
        if synthesis:
            options.append('-DSYNTHESIS=1')
        commands = ['read_slang --top weight_nonempty_property '+
                    shlex.join(options+list(map(str, dependencies))),
                    'setattr -mod -unset keep_hierarchy', 'setattr -unset keep_hierarchy',
                    'prep -top weight_nonempty_property -flatten',
                    'delete -output w:*', 'expose w:proof_nonempty',
                    'opt -full', 'memory_map', 'async2sync', 'opt -full',
                    'sat -tempinduct -seq 2 -maxsteps 5 -prove proof_nonempty 1 -verify']
        script, log = out/(key+'.ys'), out/(key+'.log')
        script.write_text('\n'.join(commands)+'\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], cwd=ROOT, check=True, stdout=stream,
                           stderr=subprocess.STDOUT, timeout=300)
        assert 'Induction step proven' in log.read_text()
        results.append({'synthesis': synthesis, 'passed': True, 'log_sha256': digest(log)})
        print(key+' PASS', flush=True)
    assert hashes == {name: digest(source_root/name) for name in hashes}
    report = {'passed': True, 'external_inputs_constrained': False,
              'scope': 'After a clock edge observing rst_n=0',
              'property': 'o_weight_write_en implies at least one asserted o_weight_write_mask bit',
              'source_sha256': hashes, 'test_sha256': digest(Path(__file__)), 'profiles': results}
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
