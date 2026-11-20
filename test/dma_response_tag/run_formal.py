#!/usr/bin/env python3
"""证明 DMA 返回标签在任意状态输入和全部标签位上的等价性。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/dma/axi_dual_block_dma.sv'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def parameter(source):
    match = re.search(r'    localparam bit p_response_tag_use_lut =.*?`endif\n', source, re.S)
    return match[0] if match else ''


def tag_body(source):
    start = source.find('    if (p_response_tag_use_lut) begin : g_response_tag_fpga')
    if start >= 0:
        return source[start:source.index('    assign rd_finish_tag', start)]
    return re.search(r'    assign rd_response_tag\s*=.*?;\n', source, re.S)[0]


def unit(source, label):
    return 'module '+label+''' #(parameter int RD_TAG_WIDTH=3)(
  input logic fe_wr_valid, win_frontend_active, conv_done_r,
  input logic [RD_TAG_WIDTH-1:0] conv_tag_q, linear_response_tag,
  output logic [RD_TAG_WIDTH-1:0] rd_response_tag
);
''' + parameter(source) + tag_body(source) + '\nendmodule\n'


def read_sources(reference):
    current = (ROOT / SOURCE).read_text()
    original = subprocess.check_output(['git', 'show', reference+':'+SOURCE], cwd=ROOT, text=True)
    restored = current.replace(parameter(current), '', 1).replace(tag_body(current), tag_body(original), 1)
    assert restored == original, '返回标签选择之外的内容有变化'
    return original, current


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='7ef39f0101ebf39184d11dbdc80a4042faee75c2')
    parser.add_argument('--out', type=Path, required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    original,current=read_sources(args.reference)
    sources={}
    for label,text in (('reference',original),('current',current)):
        sources[label]=out/(label+'.sv');sources[label].write_text(unit(text,label))
    import pyosys
    library=Path(pyosys.__file__).parent/'share/xilinx/cells_sim.v'
    primitive=re.search(r'^module LUT6\b.*?^endmodule',library.read_text(),re.M|re.S)[0]
    primitive=re.sub(r'\bspecify\b.*?\bendspecify\b','',primitive,flags=re.S)
    model=out/'official_lut6.sv';model.write_text(primitive+'\n')
    report={'reference_commit':subprocess.check_output(['git','rev-parse',args.reference],cwd=ROOT,text=True).strip(),
            'source_sha256':digest(current.encode()),'reference_sha256':digest(original.encode()),
            'outside_response_tag_selection_unchanged':True,'inputs_constrained':False,
            'scope':'完整返回标签包含无效周期，前端返回、窗口占用和卷积完成条件均允许任意组合。',
            'primitive_library_sha256':digest(library.read_bytes()),'primitive_model_sha256':digest(model.read_bytes()),
            'cases':[]}
    for width in (1,2,3,4,7,8,16,32):
        for fpga in (False,True):
            mode='fpga' if fpga else 'generic';name=f'width{width}_{mode}'
            commands=[]
            for label,path in sources.items():
                files=[path]+([model] if fpga else [])
                flags='-D XILINX_FPGA -D SYNTHESIS -D YOSYS -D VERIFIC ' if fpga else '-D ASIC_SYNTHESIS '
                commands+=['read_slang --top '+label+' -GRD_TAG_WIDTH='+str(width)+' '+flags+
                           ' '.join(shlex.quote(str(p)) for p in files),
                           'prep -top '+label+' -flatten','opt -full','design -stash '+label]
            commands+=['design -copy-from reference reference','design -copy-from current current',
                       'miter -equiv -flatten reference current comparison','hierarchy -top comparison','opt -full',
                       'sat -verify -prove trigger 0 -show-inputs -show-outputs']
            script,log=out/(name+'.ys'),out/(name+'.log');script.write_text('\n'.join(commands)+'\n')
            command=[sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)]
            with log.open('w') as stream:
                subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
            assert 'SAT proof finished - no model found: SUCCESS!' in log.read_text()
            report['cases'].append({'rd_tag_width':width,'implementation':mode,'passed':True,
                                    'compared_bits':width,'command':command,
                                    'script_sha256':digest(script.read_bytes()),'log_sha256':digest(log.read_bytes())})
            print(name+': passed',flush=True)
    assert current==(ROOT/SOURCE).read_text()
    report['passed']=True
    report['test_script_sha256']=digest(Path(__file__).read_bytes())
    report['model_sha256']={label:digest(path.read_bytes()) for label,path in sources.items()}
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    main()
