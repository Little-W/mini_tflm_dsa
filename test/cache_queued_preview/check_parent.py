#!/usr/bin/env python3
"""检查完整缓存的并行读取变换及关闭预读时的逐周期兼容性。"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import hashlib
import json
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
MODULES = tuple('rtl/npu/dma/cache/' + name for name in (
    'conv_windowed_cache.sv', 'conv_cache_request_path.sv', 'conv_cache_metadata_way.sv',
    'conv_cache_prefetch_priority.sv'))
PROFILES = (
    dict(SETS=2, WAYS=1, LINE_BYTES=8, BUS_WIDTH=32, READ_WIDTH=32, DEMAND_DEPTH=1),
    dict(SETS=2, WAYS=2, LINE_BYTES=16, BUS_WIDTH=32, READ_WIDTH=32, DEMAND_DEPTH=2),
    dict(SETS=4, WAYS=1, LINE_BYTES=32, BUS_WIDTH=64, READ_WIDTH=64, DEMAND_DEPTH=4),
    dict(SETS=16, WAYS=2, LINE_BYTES=128, BUS_WIDTH=64, READ_WIDTH=64, DEMAND_DEPTH=2),
)
MODES = (('generic', ['-USYNTHESIS', '-UXILINX_FPGA']),
         ('fpga', ['-DSYNTHESIS=1', '-DXILINX_FPGA=1']))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='3f4bc2a97dfecf0ec38ad49d704c2ee4ee7f8365')
    parser.add_argument('--preview', type=int, choices=(0, 1), default=1)
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    resolver = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    initial = []
    for relative in MODULES:
        path = out/'reference'/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if args.preview and path.name == 'conv_cache_request_path.sv':
            path.write_bytes((Path(__file__).parent/'reference_request_path.sv').read_bytes())
        else:
            path.write_bytes(subprocess.check_output(['git','show',args.reference+':'+relative],cwd=ROOT))
        initial.append(path)
    sources = {'reference':resolver(initial, ROOT),
               'current':resolver([ROOT/MODULES[0]], ROOT)}
    hashes = {str(path):digest(path) for paths in sources.values() for path in paths}
    cases = []
    # 这些名称表示组合中间值，其中部分仅参与四态计算；所有寄存状态和公开输出保留。
    renamed_combinational = ('w:u_request_path.g_queued_lookup_qualification.* '
                            'w:u_request_path.u_input_conflict.* '
                            'w:g_metadata_way*.u_metadata.g_current_lookup_valid.lookup_candidate_valid')
    for mode, flags in MODES:
        for index, parameters in enumerate(PROFILES):
            options = [f'-G{name}={value}' for name,value in parameters.items()]
            options += [f'-Gp_preview_request={args.preview}']
            commands=[]
            for label, paths in sources.items():
                commands += ['read_slang --top conv_windowed_cache '+shlex.join(flags+options+list(map(str,paths))),
                    'setattr -mod -unset keep_hierarchy','setattr -unset keep_hierarchy',
                    'prep -top conv_windowed_cache -flatten','memory_map','async2sync','opt -full',
                    'rename -hide '+renamed_combinational,f'rename -top {label}',f'design -stash {label}']
            commands += ['design -copy-from reference -as reference reference',
                'design -copy-from current -as current current','equiv_make reference current proof',
                'hierarchy -top proof','opt -full','equiv_simple -short -seq 1',
                'select *','equiv_induct -seq 2','equiv_simple -seq 1','opt_clean','equiv_status -assert']
            script=out/f'{mode}_{index}.ys'; script.write_text('\n'.join(commands)+'\n')
            cases.append((mode,flags,parameters,script,out/f'{mode}_{index}.log'))

    def execute(case):
        mode,flags,parameters,script,log=case
        with log.open('w') as stream:
            subprocess.run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],
                           stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=600)
        text=log.read_text();counts=re.findall(r'Found (\d+) \$equiv cells',text)
        assert counts and 'Equivalence successfully proven!' in text
        result=dict(mode=mode,macro_options=flags,parameters=parameters,bits=int(counts[-1]),
                    passed=True,log_sha256=digest(log))
        print(json.dumps(result),flush=True);return result
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results=list(pool.map(execute,cases))
    assert all(digest(path)==expected for path,expected in hashes.items())
    report=dict(passed=True,preview=args.preview,reference_commit=args.reference,
                source_sha256=hashes,runner_sha256=digest(__file__),input_constraints=[],
                parent_outputs_and_state_every_cycle=True,formal=results)
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__ == '__main__':
    main()
