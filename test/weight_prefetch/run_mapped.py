#!/usr/bin/env python3
"""用官方器件原语检查完整阵列综合网表的矩阵数值与输出周期。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[2]

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapped',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--verilator',default='verilator')
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    mapped=args.mapped.resolve()
    netlist=out/'ws_systolic_array_mapped.v'
    source=mapped.read_text()
    if source.count('module ws_systolic_array(')!=1:raise RuntimeError('Unexpected mapped module')
    netlist.write_text(source.replace('module ws_systolic_array(','module ws_systolic_array_mapped('))
    model=json.loads(mapped.with_suffix('.json').read_text())['modules']['ws_systolic_array']
    names=sorted({cell['type'] for cell in model['cells'].values()} | {'BUFG','IBUF','OBUF'})
    import pyosys
    library=Path(pyosys.__file__).parent/'share/xilinx/cells_sim.v'
    library_text=library.read_text();models=[]
    for name in names:
        match=re.search(r'^module '+re.escape(name)+r'\b.*?^endmodule',library_text,re.M|re.S)
        if not match:raise RuntimeError('Missing official primitive: '+name)
        models.append(match[0])
    primitives=out/'xilinx_primitives.sv';primitives.write_text('\n\n'.join(models)+'\n')
    original=ROOT/'test/weight_prefetch/array_tb.sv'
    bench=out/'array_mapped_tb.sv'
    text=original.read_text()
    text=text.replace('    ws_systolic_array #(.SIZE(SIZE)', '    wire signed [31:0] rtl_sum [SIZE];\n    ws_systolic_array #(.SIZE(SIZE)',1)
    text=text.replace('.sum_in(initial_sum), .sum_out(output_row)', '.sum_in(initial_sum), .sum_out(rtl_sum)',1)
    text=text.replace('endmodule','''    wire [255:0] mapped_weight, mapped_data;
    wire [511:0] mapped_sum, mapped_result;
    for(genvar lane=0;lane<16;lane++)begin:g_pack
        // 升序非打包数组经展开后，索引零对应打包端口的最高位段。
        assign mapped_weight[16*(15-lane)+:16]=weight_out[lane];
        assign mapped_data[16*(15-lane)+:16]=input_row[lane];
        assign mapped_sum[32*(15-lane)+:32]=initial_sum[lane];
        assign output_row[lane]=mapped_result[32*(15-lane)+:32];
        always_ff @(posedge clk) if(rst_n && output_valid)
            assert(output_row[lane]==rtl_sum[lane]);
    end
    ws_systolic_array_mapped u_mapped (
        .clk(clk),.rst_n(rst_n),.weight_commit(weight_commit),.store_weight_req(store_weight_req),
        .weight_in(mapped_weight),.data_in(mapped_data),.sum_in(mapped_sum),.sum_out(mapped_result)
    );
endmodule''')
    bench.write_text(text)
    sources=[bench,ROOT/'test/weight_prefetch/array_main.cpp',ROOT/'rtl/npu/loaders/kernel_loader_buffer.sv',
             ROOT/'rtl/common/REGFILE.v',ROOT/'rtl/npu/compute/ws_systolic_cell.sv',
             ROOT/'rtl/npu/compute/ws_systolic_array.sv',netlist,primitives]
    hashes={str(p.relative_to(ROOT)):digest(p) for p in sources}
    flags='-std=c++20 -O1 -fsanitize=undefined -fno-sanitize-recover=all -DTEST_SIZE=16 -DTEST_WEIGHT_WIDTH=16 --param=ggc-min-expand=10 --param=ggc-min-heapsize=32768'
    command=[args.verilator,'--cc','--exe','--build','-j','1','--assert','-Wno-fatal',
             '--output-split','20000','--output-split-cfuncs','100','--top-module','dip_weight_tb',
             '--Mdir',str(out/'obj'),'-GSIZE=16','-GWEIGHT_WIDTH=16','-CFLAGS',flags,
             '-LDFLAGS','-fsanitize=undefined','-MAKEFLAGS','CFG_CXXFLAGS_PCH_I=-include OPT_FAST=-O1 OPT_SLOW=-O0 OPT_GLOBAL=-O0',
             *map(str,sources)]
    with (out/'build.log').open('w') as log:
        subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=1200)
    binary=out/'obj/Vdip_weight_tb'
    result=subprocess.run([str(binary)],cwd=ROOT,capture_output=True,text=True,timeout=120)
    (out/'run.log').write_text(result.stdout+result.stderr)
    result.check_returncode()
    record=json.loads(result.stdout.strip().splitlines()[-1])
    if not record['passed']:raise RuntimeError('Mapped array verification failed')
    if hashes!={str(p.relative_to(ROOT)):digest(p) for p in sources}:raise RuntimeError('Sources changed during verification')
    report={'passed':True,'source_sha256':hashes,'mapped_sha256':digest(mapped),
            'primitive_library_sha256':digest(library),'primitive_models':names,'binary_sha256':digest(binary),
            'command':command,'result':record}
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(record))

if __name__=='__main__':main()
