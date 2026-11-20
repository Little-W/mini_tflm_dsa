"""读取真实 RAM 实现并核对命令判定以外的源码保持不变。"""
import hashlib
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'test'))
from rtl_reference import read_rtl_source

SOURCES=['rtl/soc/soc_axi_ram.sv','test/models/soc_axi_ram.sv']
FUNCTION=re.compile(r'    function automatic logic axi_command_bad\(.*?    endfunction',re.S)


def snapshot(out,reference):
    out.mkdir(parents=True,exist_ok=True)
    rows=[];functions=[]
    for source in SOURCES:
        current=(ROOT/source).read_text()
        original=read_rtl_source(f'{reference}:{source}',cwd=ROOT,text=True)
        assert len(FUNCTION.findall(current))==len(FUNCTION.findall(original))==1
        old_function=FUNCTION.search(original)[0];new_function=FUNCTION.search(current)[0]
        assert FUNCTION.sub('<command>',current)==FUNCTION.sub('<command>',original),source
        functions.append((old_function,new_function))
        label='production' if source.startswith('rtl/') else 'model'
        for version,text in [('reference',original),('current',current)]:
            folder=out/label/version;folder.mkdir(parents=True,exist_ok=True)
            (folder/'soc_axi_ram.sv').write_text(text)
        rows.append({'source':source,'reference_sha256':hashlib.sha256(original.encode()).hexdigest(),
                     'current_sha256':hashlib.sha256(current.encode()).hexdigest(),
                     'only_command_function_changed':True})
    assert functions[0]==functions[1],'Production and simulation command functions differ'
    return functions[0],{'reference_commit':reference,'sources':rows,
        'production_and_model_functions_identical':True}


def miter(original,current):
    old=original.replace('axi_command_bad','command_reference')
    new=current.replace('axi_command_bad','command_current')
    return '''module command_miter #(parameter AW=32,ADDR_LSB=3)(
    input [AW-1:0] byte_addr,input [7:0] len,input [2:0] size,input [1:0] burst,
    output reference_bad,current_bad,correct);
'''+old+'\n'+new+'''
    assign reference_bad=command_reference(byte_addr,len,size,burst);
    assign current_bad=command_current(byte_addr,len,size,burst);
    assign correct=reference_bad==current_bad;
endmodule
'''
