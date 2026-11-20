#!/usr/bin/env python3
"""核对当前源码并收集配置接收、帧地址与共享银行的验证结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from run_formal import ROOT, TOP, admission, digest
sys.path.insert(0, str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    build=args.build.resolve()
    def read(name): return json.loads((build/name).read_text())
    formal=read('verified_formal/summary.json')
    numeric=read('frame_numeric/summary.json')
    allocation=read('allocation_formal/summary.json')
    assert formal['passed'] and numeric['passed'] and allocation['passed']
    # 每份报告中的全部受测源码和测试文件均须与当前文件一致。
    for label,result in (('formal',formal),('numeric',numeric),('allocation',allocation)):
        for path,expected in result['source_sha256'].items():
            if digest(ROOT/path) != expected:
                raise RuntimeError(f'Source changed for {label}: {path}')
    if {row['ready_mask_abort'] for row in numeric['profiles']} != {0,1}:
        raise RuntimeError('Both address readiness parameters must be validated')
    if not all(row['passed'] for row in numeric['profiles']):
        raise RuntimeError('Address readiness validation did not pass')
    mapping={}
    for label in ('reference','current'):
        folder=build/'mapping/results'/('admission_'+label)
        module=json.loads((folder/'mapped.json').read_text())['modules']['admission_measure']
        bit=module['netnames']['flags_q']['bits'][10]
        root=lambda name,cell,port: bit in cell['connections'].get('Q',[])
        paths=connected_paths(module,root_filter=root)
        assert paths['graph_complete']
        mapping[label]={'metrics':json.loads((folder/'metrics.json').read_text()),
            'kernel_prefetch_idle_to_output':paths,'mapped_sha256':digest(folder/'mapped.json')}
    scope={'rtl_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'admission_expression_sha256':hashlib.sha256(
            admission((ROOT/TOP).read_text(),'admission_logic').encode()).hexdigest(),
        'npu_top_sections':['配置接收表达式','帧命令接受与地址中止表达式','共享银行配置寄存器'],
        'complete_rtl_modules':['frame_address_prepare','ps_window_scheduler','onehot_check','ps_capacity_limits'],
        'independent_admission_inputs':['ia_prefetch_idle','kernel_prefetch_idle'],
        'address_numeric_parameters':{'p_size':16,'p_use_dsp':[0,1],'p_ready_mask_abort':[0,1]}}
    report={'passed':True,'source_sha256':formal['source_sha256'],'validation_scope':scope,'formal':formal,
            'frame_numeric':numeric,'shared_allocation_formal':allocation,'mapping':mapping}
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    for label,row in mapping.items():
        print(label,row['metrics']['resources']['logic_lut_cells'],
              row['kernel_prefetch_idle_to_output']['longest_register_path_cells'])


if __name__=='__main__': main()
