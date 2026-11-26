#!/usr/bin/env python3
"""测量完整矩阵控制器，并统计偏置、容量与部分和输入到发送输出的连接。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference',default='ee8e2fc6')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    reference=subprocess.check_output(['git','rev-parse',args.reference],cwd=ROOT,text=True).strip()
    parameters=dict(REG_WIDTH=32,SIZE=16,BUS_WIDTH=64,DATA_WIDTH=8,WEIGHT_WIDTH=8)
    cases={};inputs={}
    for label in ('reference','current'):
        sources=[]
        for name in ('npu_controller.sv','npu_ia_issue_select.sv'):
            path=out/label/name;path.parent.mkdir(parents=True,exist_ok=True)
            relative='rtl/npu/control/'+name
            path.write_bytes(subprocess.check_output(['git','show',reference+':'+relative],cwd=ROOT)
                             if label=='reference' else (ROOT/relative).read_bytes())
            sources.append(str(path));inputs[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
        cases[label]=dict(top='npu_controller',sources=sources,
            options=['-DSYNTHESIS=1','-DXILINX_FPGA=1',*[f'-G{k}={v}'for k,v in parameters.items()]],
            configuration=parameters)
    config=out/'cases.json';config.write_text(json.dumps(cases,indent=2)+'\n')
    subprocess.run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--case-config',config,
        '--cases',*cases,'--out',out/'mapping','--through','pre_lut'],cwd=ROOT,check=True)
    rows={}
    for label in cases:
        cost=out/'cost'/label
        subprocess.run([sys.executable,ROOT/'scripts/fpga/remap_fpga_luts.py','--source',out/'mapping'/label,
            '--out',cost,'--mode','physical-cost','--delay-target-ps','6667','--wire-delay-ps','300',
            '--max-lut-inputs','8','--discard-abc9-temporaries'],cwd=ROOT,check=True)
        module=json.loads((cost/'mapped.json').read_text())['modules']['npu_controller']
        module['cells']['analysis_output']={'type':'FDRE','connections':{'D':module['ports']['send_ia_trigger']['bits']},
            'port_directions':{'D':'input'},'attributes':{}}
        paths={}
        for port in ('ps_frame_ready','fifo_full_flag','bias_valid','bias_sleep'):
            module['cells']['analysis_input']={'type':'FDRE','connections':{'Q':module['ports'][port]['bits']},
                'port_directions':{'Q':'output'},'attributes':{}}
            paths[port]=connected_paths(module,limit=1,group_limit=1,
                root_filter=lambda n,c,p:n=='analysis_input',sink_filter=lambda n,c,p:n=='analysis_output')
            del module['cells']['analysis_input']
        summary=json.loads((cost/'summary.json').read_text())
        rows[label]=dict(summary=summary,input_to_send_paths=paths,
            mapped_sha256=hashlib.sha256((cost/'mapped.json').read_bytes()).hexdigest())
        print(label,summary['resources']['logic_lut_cells'],summary['longest_register_path_cells'],
              {p:v['longest_register_path_cells']for p,v in paths.items()},flush=True)
    assert inputs=={p:hashlib.sha256(Path(p).read_bytes()).hexdigest()for p in inputs}
    (out/'measurement.json').write_text(json.dumps(dict(reference_commit=reference,
        parameters=parameters,source_sha256=inputs,cases=rows),ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
