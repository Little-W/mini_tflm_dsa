#!/usr/bin/env python3
"""检查 PE 累加预选、完整算术行为和真实向量控制的操作码解码。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--reference-root',type=Path)
    parser.add_argument('--reference-revision',default='caace9471dafe0236f0e2a9a40b8ddb48bdb844d')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--arithmetic-summary',type=Path)
    parser.add_argument('--iverilog',default='iverilog')
    parser.add_argument('--vvp',default='vvp')
    args=parser.parse_args()
    root=args.source_root.resolve()
    out=args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    arithmetic_summary=args.arithmetic_summary.resolve() if args.arithmetic_summary else out/'arithmetic/summary.json'
    arithmetic_runner=ROOT/'test/vector_extremum/run.py'
    pe=root/'rtl/npu/conv/vector_pe.sv'
    if not args.arithmetic_summary:
        command=[sys.executable,arithmetic_runner,'--source-root',root,'--reference',args.reference_revision,
                 '--out',arithmetic_summary.parent,'--iverilog',args.iverilog,'--vvp',args.vvp]
        if args.reference_root:
            command+=['--reference-file',args.reference_root.resolve()/'rtl/npu/conv/vector_pe.sv']
        subprocess.run(list(map(str,command)),cwd=ROOT,check=True)
    arithmetic=json.loads(arithmetic_summary.read_text())
    expected_reference=None if args.reference_root else args.reference_revision
    if not arithmetic.get('passed') or arithmetic.get('reference')!=expected_reference:
        raise RuntimeError('PE 算术检查未完成或参考版本不一致')
    if arithmetic['source_sha256'].get(str(pe))!=digest(pe) or \
            arithmetic['source_sha256'].get(str(arithmetic_runner))!=digest(arithmetic_runner):
        raise RuntimeError('PE 算术检查的输入文件已变化')
    source=root/'rtl/npu/conv/vector_engine_control.sv'
    source_hash=digest(source)
    text=source.read_text()
    case=re.search(r'case\s*\(cfg\.op\).*?endcase',text,re.S)
    hadamard=re.search(r'vector_hadamard\s*<=\s*cfg\.op.*?;',text)
    if not case or not hadamard:
        raise RuntimeError('缺少向量操作码解码')
    decode=(hadamard[0]+'\n'+case[0]).replace('cfg.op','cfg_op').replace('<=','=')
    wrapper=out/'mode_decoder.sv'
    wrapper.write_text('''module mode_decoder(
  input logic [3:0] cfg_op,
  output logic equal
);
  logic vector_hadamard;
  logic [2:0] pe_op;
  always_comb begin
'''+decode+'''
  end
  assign equal=vector_hadamard == (pe_op == vector_engine_pkg::PE_MUL);
endmodule
''')
    packages=[root/'rtl/npu/conv/conv_im2col_pkg.sv',root/'rtl/npu/conv/vector_engine_pkg.sv']
    script=out/'mode_decoder.ys'
    script.write_text('read_slang --top mode_decoder '+shlex.join(map(str,packages+[wrapper]))+
                      '\nprep -top mode_decoder -flatten\nsat -verify -prove equal 1 -show-inputs -show-outputs\n')
    with (out/'mode_decoder.log').open('w') as log:
        subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                       cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=120)
    if source_hash!=digest(source):
        raise RuntimeError('操作码验证期间控制源码发生变化')
    report={'passed':True,'source_sha256':{str(source):source_hash,str(pe):digest(pe)},
            'arithmetic_summary':str(arithmetic_summary),'arithmetic_summary_sha256':digest(arithmetic_summary),
            'arithmetic':arithmetic,'operation_decode':{'passed':True,'input_codes':16},
            'test_sha256':digest(Path(__file__))}
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':True,'operation_codes':16,'preselection_modes':2}),flush=True)


if __name__=='__main__':
    main()
