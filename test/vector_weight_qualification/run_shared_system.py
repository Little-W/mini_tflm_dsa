#!/usr/bin/env python3
"""运行实际生产驱动和 AXI 顶层，检查共享权重请求及 IA 配对访问。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    executable = shutil.which(args.verilator)
    if executable is None:
        raise RuntimeError('无法找到 Verilator')
    observer = ROOT/'test/vector_weight_qualification/shared_request_observer.sv'
    frame_observer = ROOT/'test/frame_address/npu_observer.sv'
    # 能力寄存器检查采用实际 AXI 顶层的紧凑格式参数。
    original_main = ROOT/'test/vector_engine_cosim/main.cpp'
    parameter_text = (ROOT/'rtl/axi_top/npu_axil_top.sv').read_text()
    compact = re.search(r'parameter IA_COMPACT_ENABLE\s*=\s*(\d+)', parameter_text)
    assert compact
    main_text = original_main.read_text()
    marker = 'DSA_PS_CAP_IA_COMPACT|DSA_PS_CAP_SHARED;'
    assert main_text.count(marker) == 1
    main_text = main_text.replace(marker,
        f'({int(compact[1])} ? DSA_PS_CAP_IA_COMPACT : 0u)|DSA_PS_CAP_SHARED;')
    main_source = out/'main.cpp'; main_source.write_text(main_text)
    # 外部存储模型启用运行期 AXI 延迟参数，设计 RTL 保持综合条件编译。
    original_ram = ROOT/'test/models/soc_axi_ram.sv'
    ram_source = out/'soc_axi_ram.sv'
    ram_source.write_text('`undef SYNTHESIS\n'+original_ram.read_text()+'\n`define SYNTHESIS 1\n')
    text_api = runpy.run_path(str(ROOT/'test/monitors/observer_text.py'))
    models = out/'observers'; models.mkdir(exist_ok=True)
    observers = {}
    for source in sorted((ROOT/'test/monitors').glob('*.sv')):
        target = models/source.name
        target.write_text(text_api['simulation_text'](source.read_text()))
        observers[str(source)] = str(target)
    wrapper = out/'verilator_shared_requests'
    wrapper.write_text('#!'+sys.executable+'\n'+'''import os,sys,runpy
from pathlib import Path
'''+f'root=Path({str(ROOT)!r})\nobservers={observers!r}\n'+
        f'test_sources={{{str(original_main)!r}:{str(main_source)!r}, {str(original_ram)!r}:{str(ram_source)!r}}}\n'+'''
arguments=sys.argv[1:]
sources=[Path(value) for value in arguments if Path(value).suffix in ('.sv','.v') and Path(value).is_file()]
if sources:
    ordered=runpy.run_path(str(root/'scripts/rtl/source_files.py'))['with_dependencies'](sources,root)
    names={str(path) for path in sources}
    arguments=[value for value in arguments if value not in names]+list(map(str,ordered))
    arguments=[observers.get(value,value) for value in arguments]
arguments=[test_sources.get(value,value) for value in arguments]
'''+f'command={repr([executable, "--no-timing", "-DSYNTHESIS=1", "-Wno-BLKANDNBLK", "-I"+str(ROOT/"rtl/npu/conv"), "-I"+str(ROOT/"include"), str(observer), str(frame_observer)])}+arguments\n'+
                      'os.execv(command[0],command)\n')
    wrapper.chmod(0o755)
    tracked = [Path(__file__), observer, frame_observer, wrapper, main_source, ram_source]
    hashes = {str(path): digest(path) for path in tracked}
    command = [sys.executable, str(ROOT/'test/vector_engine_cosim/run.py'), '--pcr',
               '--bus-width', '64', '--bank-bytes', '8192', '--bank-count', '7',
               '--out', str(out/'system'), '--verilator', str(wrapper), '--jobs', str(args.jobs)]
    with (out/'run.log').open('w') as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    result = json.loads((out/'system/summary.json').read_text())
    assert result['passed']
    assert hashes == {str(path): digest(path) for path in tracked}
    result['request_observer_sha256'] = digest(observer)
    result['verification_inputs_sha256'] = hashes
    result['command'] = command
    (out/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print('VECTOR_SHARED_SYSTEM_PASS', flush=True)


if __name__ == '__main__':
    main()
