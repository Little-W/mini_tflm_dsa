#!/usr/bin/env python3
"""验证标签端口的同步读取、完整输出与共用写入连接。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
METADATA = Path('rtl/npu/dma/cache/conv_cache_metadata_way.sv')
STORAGE = Path('rtl/common/regfile.v')
PROFILES = ((2, 3, 1, 0), (8, 4, 1, 1), (16, 7, 1, 1),
            (32, 4, 4, 0), (128, 8, 4, 0))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normalize(text):
    text = re.sub(r'//[^\n]*|/\*.*?\*/', '', text, flags=re.S)
    return re.sub(r'\s+', '', text)


def region(text):
    start = text.index('    assign o_lookup_tag_raw =')
    end = text.index('    // 填充、命中和提示各自保存替换信息', start)
    return text[start:end]


def audit(current, reference, storage):
    if normalize(current.replace(region(current), '')) != normalize(reference.replace(region(reference), '')):
        raise ValueError('标签读取之外的元数据逻辑发生变化')
    instances = []
    for text in (reference, current):
        matches = re.findall(r'regfile\s*#\((.*?)\)\s+(u_\w+)\s*\((.*?)\);', region(text), re.S)
        if not matches:
            raise ValueError('标签存储实例未找到')
        for parameters, name, ports in matches:
            connections = {}
            for port in ('clk', 'i_wr_en', 'i_wr_addr', 'i_wr_data', 'i_wr_mask'):
                found = re.search(r'\.' + port + r'\(([^()]*)\)', ports)
                if found is None:
                    raise ValueError('写入连接缺失：' + port)
                connections[port] = normalize(found[1])
            instances.append(connections)
            for parameter, expected in (('p_data_width', 'p_tag_width'), ('p_depth', 'SETS'),
                                        ('p_addr_width', 'SI'), ('p_write_unit', 'p_tag_width')):
                if f'.{parameter}({expected})' not in normalize(parameters):
                    raise ValueError('标签存储组织改变：' + name)
            if 'p_no_change_collision' in parameters:
                raise ValueError('读取模式需要单独验证')
    if any(item != instances[0] for item in instances):
        raise ValueError('各存储体必须共享相同写入端口')
    if normalize("assign tags_i_rd_en = '1;") not in normalize(current):
        raise ValueError('标签读端口的持续使能发生变化')
    read_start = storage.rindex('    for (genvar port_index = 0; port_index < p_read_ports; port_index++) begin : g_read_port')
    read_end = storage.index('`ifdef ASIC_SRAM', read_start)
    read_body = storage[read_start:read_end].replace('mem[', 'i_contents[')
    header = storage[storage.index('module regfile'):storage.index(');', storage.index('module regfile')) + 2]
    header = header[:-2].rstrip() + ',\n    input logic [p_depth-1:0][p_data_width-1:0] i_contents\n);\n'
    return header + '\nwire [p_read_ports-1:0] read_accept=i_rd_en;\n' + read_body + '\nendmodule\n', len(instances)


def module(name, source):
    body = region(source).replace('.clk(clk)', '.i_contents(memory_state), .clk(clk)')
    return f'''module {name} #(parameter integer SETS=16,LB=7,DEMAND_DEPTH=1,PREVIEW=1,
 SI=$clog2(SETS),p_tag_width=32-LB,p_tag_read_ports=DEMAND_DEPTH==1 ? 8+PREVIEW : 5)(
 input logic clk,input logic [SETS-1:0][p_tag_width-1:0] memory_state,
 input logic tags_i_wr_en,input logic [SI-1:0]tags_i_wr_addr,
 input logic [p_tag_width-1:0]tags_i_wr_data,input logic[0:0]tags_i_wr_mask,
 input logic[p_tag_read_ports-1:0][SI-1:0]tags_i_rd_addr,
 output logic[(5+p_tag_read_ports)*p_tag_width-1:0]observed);
 logic[p_tag_read_ports-1:0]tags_i_rd_en;
 logic[p_tag_read_ports-1:0][p_tag_width-1:0]tags_raw_data;
 logic[4:0][p_tag_width-1:0]tags_o_rd_data;
 logic[p_tag_width-1:0]o_lookup_tag_raw;
 assign tags_i_rd_en='1;
{body}
 assign observed={{tags_o_rd_data,tags_raw_data}};
endmodule
'''


def proof():
    return '''module proof #(parameter integer SETS=16,LB=7,DEMAND_DEPTH=1,PREVIEW=1,
 SI=$clog2(SETS),TW=32-LB,PORTS=DEMAND_DEPTH==1?8+PREVIEW:5,
 BITS=SETS*TW+1+SI+TW+1+PORTS*SI,RESULTS=(5+PORTS)*TW)(
 input logic clk,input logic[BITS-1:0]stimulus,
 output logic equivalent,output logic[RESULTS-1:0]actual,expected);
 logic[SETS-1:0][TW-1:0]memory_state;
 logic tags_i_wr_en;
 logic[SI-1:0]tags_i_wr_addr;
 logic[TW-1:0]tags_i_wr_data;
 logic[0:0]tags_i_wr_mask;
 logic[PORTS-1:0][SI-1:0]tags_i_rd_addr;
 assign {memory_state,tags_i_wr_en,tags_i_wr_addr,tags_i_wr_data,tags_i_wr_mask,tags_i_rd_addr}=stimulus;
 reference #(.SETS(SETS),.LB(LB),.DEMAND_DEPTH(DEMAND_DEPTH),.PREVIEW(PREVIEW)) u_reference(.*,.observed(expected));
 candidate #(.SETS(SETS),.LB(LB),.DEMAND_DEPTH(DEMAND_DEPTH),.PREVIEW(PREVIEW)) u_candidate(.*,.observed(actual));
 assign equivalent=actual===expected;
endmodule
'''


def bench(sets, lb, depth, preview):
    si, width = (sets-1).bit_length(), 32-lb
    ports = 8+preview if depth==1 else 5
    bits = sets*width+1+si+width+1+ports*si
    results = (5+ports)*width
    return f'''module tb;
 logic clk=0,equivalent;
 logic[{bits-1}:0]stimulus;
 logic[{results-1}:0]actual,expected;
 integer sample,bit_index,checks=0,seed=32'h2c593ab1;
 proof #(.SETS({sets}),.LB({lb}),.DEMAND_DEPTH({depth}),.PREVIEW({preview}))dut(.*);
 initial begin
  stimulus='0;
  #1;clk=1;#1;clk=0;
  for(sample=0;sample<1024;sample=sample+1)begin
   for(bit_index=0;bit_index<{bits};bit_index=bit_index+1)
    stimulus[bit_index]=$random(seed);
   if(sample%2)stimulus[$unsigned($random(seed))%{bits}]=1'bx;
   if(sample%3)stimulus[$unsigned($random(seed))%{bits}]=1'bz;
   #1;
   if(equivalent!==1'b1)$fatal(1,"Tag read mismatch before edge sample=%0d",sample);
   clk=1;#1;
   if(equivalent!==1'b1)$fatal(1,"Tag read mismatch after edge sample=%0d",sample);
   clk=0;checks=checks+2;
  end
  $display("SYNC_TAGS_FOUR_STATE_PASS checks=%0d",checks);$finish;
 end
endmodule
'''


def run(command, log):
    with log.open('w') as stream:
        subprocess.run([str(value) for value in command],stdout=stream,stderr=subprocess.STDOUT,
                       check=True,timeout=180)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--reference-root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    root,reference,out=args.source_root.resolve(),args.reference_root.resolve(),args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    paths=[root/METADATA,reference/METADATA,root/STORAGE,reference/STORAGE]
    hashes={str(path):digest(path) for path in paths}
    if (root/STORAGE).read_bytes()!=(reference/STORAGE).read_bytes():
        raise ValueError('两侧存储实现必须相同')
    current,original=(root/METADATA).read_text(),(reference/METADATA).read_text()
    memory,instances=audit(current,original,(root/STORAGE).read_text())
    model=out/'proof.sv'
    model.write_text(memory+module('reference',original)+module('candidate',current)+proof())
    profiles=[]
    for sets,lb,depth,preview in PROFILES:
        name=f's{sets}_l{lb}_d{depth}_p{preview}'
        script=out/(name+'.ys')
        script.write_text(f'read_slang --top proof -GSETS={sets} -GLB={lb} -GDEMAND_DEPTH={depth} -GPREVIEW={preview} '+shlex.quote(str(model))+'\n'
                          'prep -top proof -flatten\ncheck -assert\n'
                          'sat -seq 2 -prove-skip 1 -verify -prove equivalent 1\n'
                          'sat -seq 1 -tempinduct-inductonly -maxsteps 1 -verify -prove equivalent 1\n')
        run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],out/(name+'.formal.log'))
        testbench,binary=out/(name+'.tb.sv'),out/(name+'.vvp')
        testbench.write_text(bench(sets,lb,depth,preview))
        run(['iverilog','-g2012','-s','tb','-o',binary,model,testbench],out/(name+'.compile.log'))
        run(['vvp',binary],out/(name+'.four_state.log'))
        binary.unlink()
        profiles.append({'sets':sets,'line_bytes':1<<lb,'demand_depth':depth,'preview':preview,
                         'passed':True,'four_state_checks':2048,
                         'formal_log_sha256':digest(out/(name+'.formal.log')),
                         'four_state_log_sha256':digest(out/(name+'.four_state.log'))})
    if hashes!={name:digest(name) for name in hashes}:raise RuntimeError('验证期间源文件发生变化')
    report={'passed':True,'write_connections_identical':True,'remaining_metadata_identical':True,
            'storage_instances_audited':instances,'memory_contents_constrained':False,
            'addresses_constrained':False,'profiles':profiles,'source_sha256':hashes,
            'checker_sha256':digest(__file__),'model_sha256':digest(model)}
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print('SYNC_TAGS_PASS',out/'summary.json',flush=True)


if __name__=='__main__':main()
