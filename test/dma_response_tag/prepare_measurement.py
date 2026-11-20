#!/usr/bin/env python3
"""提取缓存错误、前端返回、DMA 标签及仲裁器使用方的实际组合连接。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess

ROOT=Path(__file__).resolve().parents[2]
SOURCE='rtl/npu/dma/axi_dual_block_dma.sv'
SUPPORT=('rtl/npu/conv/conv_im2col_frontend.sv',
         'rtl/npu/dma/axi_block_dma_arbiter.sv','rtl/npu/dma/cache/conv_read_cache.sv')


def assignment(text,name):
    return re.search(r'\bassign\s+'+name+r'\s*=.*?;',text,re.S)[0]


def model(source,label,helpers):
    frontend=(ROOT/SUPPORT[0]).read_text();arbiter=(ROOT/SUPPORT[1]).read_text();cache=(ROOT/SUPPORT[2]).read_text()
    front_enum=re.search(r'typedef enum logic \[4:0\].*?} st_t;',frontend,re.S)[0]
    client_enum=re.search(r'typedef enum logic \[2:0\].*?} client_e;',arbiter,re.S)[0]
    wr_valid=assignment(frontend,'wr_valid').replace('wr_valid =','fe_wr_valid =')
    assert 'assign rsp_error = response_queue_error[response_head];' in cache
    raw_valid=assignment(arbiter,'dw_raw_valid')
    top='response_tag_connection'
    body='module '+top+''' (
  input logic clk,
  input logic [3:0] i_response_queue_error,
  input logic [1:0] i_response_head,
  input logic [4:0] i_frontend_state,
  input logic i_cache_rsp_valid, i_win_frontend_active, i_conv_done_r, i_dma_raw_valid,
  input logic [2:0] i_conv_tag, i_linear_tag,
  output logic [2:0] o_tag,
  output logic o_vector_raw_valid
);
  localparam int RD_TAG_WIDTH=3;
  logic [3:0] response_queue_error;
  logic [1:0] response_head;
  logic [4:0] state;
  logic cache_rsp_valid,win_frontend_active,conv_done_r,dma_raw_valid;
  logic [2:0] conv_tag_q,linear_response_tag,rd_response_tag;
  logic cache_rsp_error,fe_wr_valid,dw_raw_valid;
'''+front_enum+'\n'+client_enum+'''\n
  client_e rd_response_client;
  always_ff @(posedge clk) begin
    response_queue_error<=i_response_queue_error;
    response_head<=i_response_head;
    state<=i_frontend_state;
    cache_rsp_valid<=i_cache_rsp_valid;
    win_frontend_active<=i_win_frontend_active;
    conv_done_r<=i_conv_done_r;
    dma_raw_valid<=i_dma_raw_valid;
    conv_tag_q<=i_conv_tag;
    linear_response_tag<=i_linear_tag;
    o_tag<=rd_response_tag;
    o_vector_raw_valid<=dw_raw_valid;
  end
  assign cache_rsp_error=response_queue_error[response_head];
  assign rd_response_client=client_e'(rd_response_tag);
'''+wr_valid+'\n'+helpers['parameter'](source)+helpers['tag_body'](source)+raw_valid+'\nendmodule\n'
    return body


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference',default='7ef39f0101ebf39184d11dbdc80a4042faee75c2');p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    helpers=runpy.run_path(str(ROOT/'test/dma_response_tag/run_formal.py'))
    original,current=helpers['read_sources'](a.reference)
    cases={};record={}
    for label,text in (('reference',original),('current',current)):
        path=out/(label+'.sv');path.write_text(model(text,label,helpers))
        cases[label]={'top':'response_tag_connection','sources':[str(path)],
            'options':['-D','SYNTHESIS=1','-D','XILINX_FPGA=1'],
            'configuration':'Actual cache response selection, frontend write valid, 3-bit DMA tag and vector raw-valid decode'}
        record[label]={'source_sha256':hashlib.sha256(text.encode()).hexdigest(),
                       'model_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    for name in SUPPORT:
        expected=subprocess.check_output(['git','show',a.reference+':'+name],cwd=ROOT)
        assert expected==(ROOT/name).read_bytes(), name
    (out/'cases.json').write_text(json.dumps(cases,indent=2)+'\n')
    (out/'source.json').write_text(json.dumps({'reference_commit':a.reference,'cases':record,
        'support_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in SUPPORT},
        'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},indent=2)+'\n')
    print(out/'cases.json')


if __name__=='__main__':main()
