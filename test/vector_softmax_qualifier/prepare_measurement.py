#!/usr/bin/env python3
"""生成实际累加器写入过程的寄存器间映射输入。"""
import argparse
import hashlib
import json
import re
from pathlib import Path
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/conv/vector_engine.sv'


def with_softmax_control(text, source, softmax):
    """连接实际 Softmax 响应接收条件，保留数据符号检查与写使能的组合关系。"""
    assert text.count('input logic i_soft_exp_we,')==1
    assert text.count('soft_exp_we <= i_soft_exp_we;')==1
    text=text.replace('input logic i_soft_exp_we,',
        'input logic [4:0] i_soft_state,\n  input logic i_rd_done,i_rd_error,',1)
    text=text.replace('logic soft_exp_we;',
        'logic soft_exp_we;\nlogic [4:0] soft_state;\nlogic rd_done,rd_error,soft_lut_rsp_valid;',1)
    text=text.replace('soft_exp_we <= i_soft_exp_we;',
        'soft_state <= i_soft_state;\nrd_done <= i_rd_done;\nrd_error <= i_rd_error;',1)
    statement=re.search(r'assign soft_lut_rsp_valid\s*=.*?;',source,re.S)[0]
    instance=statement+"""
  softmax_write_control u_softmax_write_control(
    .c_st(soft_state),.lut_rsp_valid(soft_lut_rsp_valid),.lut_rsp_data(soft_exp_data),
    .lut_rsp_error(rd_error),.exp_we(soft_exp_we));
"""
    text=text.replace('always_ff @(posedge clk) begin',instance+'\nalways_ff @(posedge clk) begin',1)
    declaration=re.search(r'  typedef enum logic \[4:0\].*?} state_t;',softmax,re.S)[0]
    accept=re.search(r'assign lut_accept_fire\s*=.*?;',softmax,re.S)[0]
    enable=re.search(r'assign exp_we\s*=.*?;',softmax,re.S)[0]
    text+='module softmax_write_control(input logic [4:0] c_st,input logic lut_rsp_valid,\n'
    text+='  input logic [31:0] lut_rsp_data,input logic lut_rsp_error,output logic exp_we);\n'
    text+=declaration+'\nlogic lut_accept_fire;\n'+accept+'\n'+enable+'\nendmodule\n'
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='7ef39f0101ebf39184d11dbdc80a4042faee75c2')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--softmax-control',action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).with_name('run_formal.py')
    helpers = runpy.run_path(str(script))
    current = (ROOT / SOURCE).read_text()
    reference = subprocess.check_output(['git', 'show', args.reference+':'+SOURCE], cwd=ROOT, text=True)
    assert current.replace(helpers['section'](current), helpers['section'](reference), 1) == reference
    cases = {}
    sources = {}
    for label, text in (('reference', reference), ('current', current)):
        path = out / (label+'.sv')
        model=helpers['unit'](text, 'accumulator_write', 64, 16, 8, False)
        if args.softmax_control:
            model=with_softmax_control(model,text,(ROOT/'rtl/npu/conv/vector_softmax.sv').read_text())
        path.write_text(model)
        sources[label] = {'source_sha256': hashlib.sha256(text.encode()).hexdigest(),
                          'model_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        cases[label] = {
            'top': 'accumulator_write',
            'sources': [str(ROOT/'rtl/npu/conv/conv_im2col_pkg.sv'),
                        str(ROOT/'rtl/npu/conv/vector_engine_pkg.sv'), str(path)],
            'options': ['-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1'],
            'configuration': 'Actual accumulator and RHS writes; TILE16 PE8 BUS64; registered arbitrary inputs',
        }
    (out/'cases.json').write_text(json.dumps(cases, indent=2)+'\n')
    (out/'source.json').write_text(json.dumps({
        'reference_commit': subprocess.check_output(['git', 'rev-parse', args.reference], cwd=ROOT, text=True).strip(),
        'cases': sources, 'softmax_control_included':args.softmax_control,
        'softmax_sha256':hashlib.sha256((ROOT/'rtl/npu/conv/vector_softmax.sv').read_bytes()).hexdigest(),
        'generator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'formal_script_sha256': hashlib.sha256(script.read_bytes()).hexdigest(),
    }, indent=2)+'\n')
    print(out/'cases.json')


if __name__ == '__main__':
    main()
