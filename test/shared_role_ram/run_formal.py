#!/usr/bin/env python3
"""证明共享存储全部写入和读取命令，以及配置首次读取后的持续返回行为。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/buffers/ia_ps_channel_ram.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def instrument(source, name):
    source = source.replace('module ia_ps_channel_ram #(', 'module '+name+' #(', 1)
    marker = '    input  wire logic clk'
    assert marker in source
    source = source.replace(marker,
        '    input wire logic [16:0][127:0] proof_words, // 相同地址读取的任意返回内容\n'+marker, 1)
    blocks = [
        ('regfile #(.p_data_width(128), .p_depth(p_rows)', 'proof_words[0]'),
        ('regfile #(.p_data_width(128), .p_depth(p_chunk_rows)', 'proof_words[1+4*(bank-1)+channel]'),
        ('regfile #(.p_data_width(128), .p_depth(p_fixed_rows)', 'proof_words[1+4*(p_max_ia_banks-1)+channel]'),
    ]
    if 'ia_ps_role_ram #(' in source:
        blocks.append(('ia_ps_role_ram #(', 'proof_words[1+4*(bank-1)+channel]'))
    for start, word in blocks:
        position = source.index(start)
        port = source.index('.clk(clk)', position)
        source = source[:port] + '.i_proof_word('+word+'), ' + source[port:]
    for depth in ['p_rows','p_fixed_rows']:
        source = source.replace('regfile #(.p_data_width(128), .p_depth('+depth+')',
                                'proof_common_memory #(.p_data_width(128), .p_depth('+depth+')')
    return source


MODELS = '''
// 未改变的专用 RAM 逐位检查全部命令，其共用返回值可以每拍任意变化。
module proof_common_memory #(
 parameter int p_data_width=128,p_depth=128,p_addr_width=$clog2(p_depth),p_write_unit=8
)(input logic clk,i_wr_en,i_rd_en,
 input logic [p_addr_width-1:0] i_wr_addr,i_rd_addr,
 input logic [p_data_width-1:0] i_wr_data,
 input logic [p_data_width/p_write_unit-1:0] i_wr_mask,
 input logic [127:0] i_proof_word,
 output logic [p_data_width-1:0] o_rd_data);
 assign o_rd_data=i_proof_word;
endmodule
// 命令另行逐位证明；相同物理地址的读取返回使用任意逐周期变化的数据。
module regfile #(
 parameter int p_data_width=128,p_depth=128,p_addr_width=$clog2(p_depth),p_write_unit=8
)(input logic clk,i_wr_en,i_rd_en,
 input logic [p_addr_width-1:0] i_wr_addr,i_rd_addr,
 input logic [p_data_width-1:0] i_wr_data,
 input logic [p_data_width/p_write_unit-1:0] i_wr_mask,
 input logic [127:0] i_proof_word,
 output logic [p_data_width-1:0] o_rd_data);
 always_ff @(posedge clk)if(i_rd_en)o_rd_data<=i_proof_word;
endmodule
module ia_ps_role_ram #(parameter p_depth=128,p_addr_width=$clog2(p_depth))(
 input logic clk,i_a_enable,i_a_write,i_b_enable,i_b_write,
 input logic i_access_enable=1'b1, // 两个物理端口的全局访问许可。
 input logic [p_addr_width-1:0] i_a_addr,i_b_addr,
 input logic [127:0] i_a_data,i_b_data,i_proof_word,
 input logic [15:0] i_a_mask,
 output logic [127:0] o_a_data,o_b_data);
 always_ff @(posedge clk)begin
  if(i_access_enable && (i_a_enable || i_a_write))o_a_data<=i_proof_word;
  if(i_access_enable && (i_b_enable || i_b_write))o_b_data<=i_proof_word;
 end
endmodule
'''


def miter(reference, current):
    ports = '''
 input logic clk,rst_n,i_access_enable,i_cfg_valid,
 input logic [p_bank_count_width-1:0] i_cfg_ia_banks,
 input logic [1:0] i_ia_read_en,i_ia_write_en,
 input logic [p_addr_width-1:0] i_ia_read_addr[2],i_ia_write_addr[2],
 input logic [127:0] i_ia_write_data[2],i_ia_shared_write_data,
 input logic [15:0] i_ia_write_mask[2],
 input logic [3:0] i_ps_read_en,i_ps_write_en,
 input logic [p_addr_width-1:0] i_ps_read_addr[4],i_ps_write_addr[4],
 input logic [127:0] i_ps_write_data[4],
 input logic [16:0][127:0] proof_words,
 output logic equivalent
'''
    body = instrument(reference, 'channel_reference') + instrument(current, 'channel_current') + MODELS
    body += '''module role_miter #(
 parameter p_bank_bytes=8192,p_total_bytes=57344,p_shared_write_stage=1,p_paired_ia_ports=0,p_ia_nonempty_writes=0,
 parameter p_addr_width=$clog2(p_total_bytes/16),
 parameter p_bank_count_width=$clog2(p_total_bytes/p_bank_bytes+1)
) ('''+ports+''');
 localparam p_max_ia_banks=p_total_bytes/p_bank_bytes>=8?4:2;
 logic reference_fault,current_fault;
 wire [127:0] reference_ia_data[2],current_ia_data[2];
 wire [127:0] reference_ps_data[4],current_ps_data[4];
 logic [1:0] ia_seen;
 logic [3:0] ps_seen;
 wire [1:0] ia_history;
 wire [3:0] ps_history,fixed_commands,ps_return_equal;
 wire [p_max_ia_banks-2:0][3:0] shared_commands;
 wire [p_max_ia_banks-2:0][3:0] shared_history;
 wire [p_max_ia_banks-2:0][3:0] ia_chunk_read,ps_chunk_read;
 wire [p_max_ia_banks-2:0][1:0] ia_selection_history;
 wire [p_max_ia_banks-2:0][3:0] ps_selection_history;
 wire [p_max_ia_banks-2:0] shared_return_equal;
'''
    inputs = ('clk','rst_n','i_access_enable','i_cfg_valid','i_cfg_ia_banks','i_ia_read_en',
        'i_ia_write_en','i_ia_read_addr','i_ia_write_addr','i_ia_write_data','i_ia_shared_write_data',
        'i_ia_write_mask','i_ps_read_en','i_ps_write_en','i_ps_read_addr','i_ps_write_addr',
        'i_ps_write_data','proof_words')
    parameters = ('p_bank_bytes','p_total_bytes','p_shared_write_stage','p_paired_ia_ports','p_ia_nonempty_writes')
    for label in ('reference','current'):
        fields = [f'.{x}({x})' for x in parameters]
        if label == 'current':
            fields.append(".p_allow_inactive_return_updates(1'b1)")
        connections = [f'.{x}({x})' for x in inputs]
        connections += [f'.o_capacity_fault({label}_fault)',f'.o_ia_read_data({label}_ia_data)',
                        f'.o_ps_read_data({label}_ps_data)']
        body += f' channel_{label} #('+','.join(fields)+f') u_{label}('+','.join(connections)+');\n'
    body += '''
 always_ff @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin ia_seen<='0;ps_seen<='0;end
  else if(i_cfg_valid)begin ia_seen<='0;ps_seen<='0;end
  else begin
   for(integer p=0;p<2;p++)begin
    if(u_current.memory_access_enabled && i_ia_read_en[p] && u_current.ia_read_range[p] &&
       (!p_paired_ia_ports || p_max_ia_banks!=2 || p==0 || u_current.ia_read_bank[p]==1))
      ia_seen[p]<=1'b1;
   end
   for(integer p=0;p<4;p++)
    if(u_current.memory_access_enabled && i_ps_read_en[p] && u_current.ps_read_range[p])
      ps_seen[p]<=1'b1;
  end
 end
 for(genvar p=0;p<2;p++)begin:g_ia
  assign ia_history[p]=u_reference.ia_return_bank_q[p]==u_current.ia_return_bank_q[p] &&
    (!ia_seen[p] || current_fault || reference_ia_data[p]==current_ia_data[p]);
 end
 for(genvar p=0;p<4;p++)begin:g_ps
  assign ps_history[p]=!ps_seen[p] || current_fault || reference_ps_data[p]==current_ps_data[p];
  assign ps_return_equal[p]=u_reference.ps_return_select_q[p]==u_current.ps_return_select_q[p];
'''
    def commands(a, b):
        return f'''({a}.i_rd_en=={b}.i_rd_en && {a}.i_wr_en=={b}.i_wr_en &&
 (!{a}.i_rd_en || {a}.i_rd_addr=={b}.i_rd_addr) &&
 (!{a}.i_wr_en || ({{{a}.i_wr_addr,{a}.i_wr_mask,{a}.i_wr_data}}==
                    {{{b}.i_wr_addr,{b}.i_wr_mask,{b}.i_wr_data}})))'''
    body += ' assign fixed_commands[p]='+commands('u_reference.g_fixed_channel[p].u_ram',
                                                'u_current.g_fixed_channel[p].u_ram')+';\n end\n'
    body += '''
 for(genvar bank=1;bank<p_max_ia_banks;bank++)begin:g_bank
  assign shared_return_equal[bank-1]=u_reference.g_shared_bank[bank].return_chunk_q==
                                     u_current.g_shared_bank[bank].return_chunk_q;
  for(genvar p=0;p<2;p++)begin:g_ia_selection
   wire selects_bank=(p_paired_ia_ports && p_max_ia_banks==2 && p==1) ? bank==1 :
     u_current.ia_return_bank_q[p]==bank;
   assign ia_selection_history[bank-1][p]=!ia_seen[p] || current_fault || !selects_bank ||
     ia_chunk_read[bank-1][u_current.g_shared_bank[bank].return_chunk_q];
  end
  for(genvar p=0;p<4;p++)begin:g_ps_selection
   assign ps_selection_history[bank-1][p]=!ps_seen[p] || current_fault ||
    u_current.ps_return_select_q[p]!=bank || ps_chunk_read[bank-1][p];
  end
  for(genvar channel=0;channel<4;channel++)begin:g_channel
'''
    a = 'u_reference.g_shared_bank[bank].g_channel[channel].u_ram'
    b = 'u_current.g_shared_bank[bank].g_channel[channel].g_qualified_response.u_ram'
    c = 'u_current.g_shared_bank[bank]'
    body += f'''
   logic ia_chunk_seen,ps_chunk_seen;
   always_ff @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin ia_chunk_seen<=1'b0;ps_chunk_seen<=1'b0;end
    else if(i_cfg_valid)begin ia_chunk_seen<=1'b0;ps_chunk_seen<=1'b0;end
    else if({a}.i_rd_en)begin
     if({c}.ia_selected)ia_chunk_seen<=1'b1;
     else ps_chunk_seen<=1'b1;
    end
   end
   assign ia_chunk_read[bank-1][channel]=ia_chunk_seen;
   assign ps_chunk_read[bank-1][channel]=ps_chunk_seen;
   assign shared_history[bank-1][channel]=
    (!ia_chunk_seen || ({c}.ia_selected && {a}.o_rd_data=={b}.o_b_data)) &&
    (!ps_chunk_seen || (!{c}.ia_selected && {a}.o_rd_data=={b}.o_a_data));
   wire a_write={b}.i_access_enable && {b}.i_a_write;
   wire b_write={b}.i_access_enable && {b}.i_b_write;
   wire a_read={b}.i_access_enable && {b}.i_a_enable;
   wire b_read={b}.i_access_enable && {b}.i_b_enable;
   wire [15:0] reference_mask={{16{{{a}.i_wr_en}}}} & {a}.i_wr_mask;
   wire [15:0] current_mask=({{16{{a_write}}}} & {b}.i_a_mask) | {{16{{b_write}}}};
   assign shared_commands[bank-1][channel]=
    reference_mask==current_mask && !(a_write && b_write) &&
    (!a_write || {c}.ia_selected) && (!b_write || !{c}.ia_selected) &&
    (!(a_write && (|{b}.i_a_mask)) || {a}.i_wr_addr=={b}.i_a_addr) &&
    (!b_write || {a}.i_wr_addr=={b}.i_b_addr) &&
    (!{a}.i_rd_en || ({c}.ia_selected ?
      (b_read && {a}.i_rd_addr=={b}.i_b_addr) :
      (a_read && {a}.i_rd_addr=={b}.i_a_addr))) &&
    (!{c}.ia_selected || b_read=={a}.i_rd_en) &&
    ({c}.ia_selected || a_read=={a}.i_rd_en) &&
    (({{16{{a_write}}}} & {b}.i_a_mask)=='0 || {a}.i_wr_data=={b}.i_a_data) &&
    (!b_write || {a}.i_wr_data=={b}.i_b_data);
  end
 end
 assign equivalent=reference_fault==current_fault &&
   u_reference.configured_q==u_current.configured_q &&
   u_reference.ia_banks_q==u_current.ia_banks_q &&
   u_reference.ia_banks_q==u_current.ia_layout_banks &&
   u_reference.ia_layout_banks==u_current.ia_layout_banks &&
   (&ia_history) && (&ps_history) && (&fixed_commands) &&
   (&shared_commands) && (&shared_history) && (&shared_return_equal) && (&ps_return_equal) &&
   (&ia_selection_history) && (&ps_selection_history) &&
   {commands('u_reference.u_ia_ram','u_current.u_ia_ram')};
endmodule
'''
    return body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='19d62e18')
    parser.add_argument('--profiles', nargs='+', default=['2048:6:0:0','2048:8:1:0','8192:7:1:0','8192:7:1:1','8192:7:1:1:1','8192:9:1:0'])
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve();out.mkdir(parents=True, exist_ok=True)
    original = subprocess.check_output(['git','show',args.reference+':'+str(SOURCE)],cwd=ROOT,text=True)
    current = (ROOT/SOURCE).read_text()
    target=out/'miter.sv';target.write_text(miter(original,current))
    records=[]
    for profile in args.profiles:
        values=list(map(int,profile.split(':')))
        size,banks,stage,paired=values[:4]
        nonempty=values[4] if len(values)>4 else 0
        parameters=dict(p_bank_bytes=size,p_total_bytes=size*banks,
                        p_shared_write_stage=stage,p_paired_ia_ports=paired,p_ia_nonempty_writes=nonempty)
        label=profile.replace(':','_');script,log=out/(label+'.ys'),out/(label+'.log')
        script.write_text('read_slang --top role_miter -DSYNTHESIS=1 -DXILINX_FPGA=1 '+
            shlex.join([f'-G{k}={v}'for k,v in parameters.items()]+[str(target)])+'\n'
            'prep -top role_miter -flatten\nasync2sync\nopt_clean\n'
            'sat -verify -tempinduct -seq 2 -maxsteps 8 -set-at 1 rst_n 0 -prove equivalent 1\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],
                cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=300)
        assert 'Induction step proven: SUCCESS!' in log.read_text()
        records.append(dict(parameters=parameters,passed=True,log_sha256=digest(log)))
        print('SHARED_ROLE_FORMAL_PASS',label,flush=True)
    assert current==(ROOT/SOURCE).read_text()
    report=dict(passed=True,reference_revision=args.reference,source_sha256=digest(ROOT/SOURCE),
        role_storage_sha256=digest(ROOT/'rtl/npu/buffers/ia_ps_role_ram.sv'),
        input_constraints='首次采样复位，其后全部功能输入和复位自由',
        memory_model='未改变的 RAM 共用任意逐周期返回；修改的 RAM 使用同步任意读值；全部 RAM 逐位比较读写地址、有效掩码和写数据',
        response_scope='本次配置首次接受读取后持续比较全部返回周期，配置或故障终止该访问上下文',
        profiles=records,miter_sha256=digest(target),test_sha256=digest(Path(__file__)))
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    main()
