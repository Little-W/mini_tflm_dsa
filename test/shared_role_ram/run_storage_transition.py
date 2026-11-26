#!/usr/bin/env python3
"""证明实际双端口 RAM 与单写单读 RAM 的任意共同内容保持相同更新及读取结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
WRAPPER=r'''
// 模块作用：比较两种共享存储端口在任意共同内容下的一步更新和同步读结果。
// 每次展开检查一个字节，遍历全部字节后覆盖完整的 128 位数据。
module storage_transition #(
 parameter p_depth=4,
 parameter p_addr_width=$clog2(p_depth),
 parameter p_byte_index=0
)(
 input logic clk,                                      // 同步存储访问时钟。
 input logic access_enable,                            // 本周期统一允许存储读写。
 input logic ia_owner,                                 // 当前共享存储块归属 IA 通路。
 input logic ia_read,                                  // IA 读取请求。
 input logic ia_write,                                 // IA 写入请求。
 input logic ps_read,                                  // 部分和读取请求。
 input logic ps_write,                                 // 部分和写入请求。
 input logic [p_addr_width-1:0] ia_read_addr,            // IA 读取字地址。
 input logic [p_addr_width-1:0] ia_write_addr,           // IA 写入字地址。
 input logic [p_addr_width-1:0] ps_read_addr,            // 部分和读取字地址。
 input logic [p_addr_width-1:0] ps_write_addr,           // 部分和写入字地址。
 input logic [127:0] ia_data,                           // IA 写入数据。
 input logic [127:0] ps_data,                           // 部分和写入数据。
 input logic [15:0] ia_mask,                            // IA 逐字节写入掩码。
 input logic [p_addr_width-1:0] watched_row,             // 自由选择的待检查存储行。
 output logic watch_stable,                            // 待检查行在相邻证明时刻保持相同。
 output logic memory_equal,                            // 任意所选存储行的被检查字节相同。
 output logic equivalent                               // 存储内容和有效同步返回均相同。
);
 // 所有者决定生效的请求；两个逻辑通路保留独立读写地址。
 wire read_enable=access_enable && (ia_owner?ia_read:ps_read);
 wire write_enable=access_enable && (ia_owner?ia_write:ps_write);
 wire [p_addr_width-1:0] read_addr=ia_owner?ia_read_addr:ps_read_addr;
 wire [p_addr_width-1:0] write_addr=ia_owner?ia_write_addr:ps_write_addr;
 wire [127:0] write_data=ia_owner?ia_data:ps_data;
 wire [15:0] write_mask=ia_owner?ia_mask:16'hffff;
 wire [127:0] reference_data,ia_return,ps_return;
 logic previous_read,previous_owner;
 logic [p_addr_width-1:0] previous_read_addr;
 logic [p_addr_width-1:0] previous_watched_row;
 // 证明时保持观察行地址不变；初值自由，因此一项证明覆盖全部存储行。
 assign watch_stable=previous_watched_row==watched_row;
 regfile #(.p_data_width(128),.p_depth(p_depth),.p_addr_width(p_addr_width),.p_write_unit(8)) u_reference(
  .clk(clk),.i_wr_en(write_enable),.i_wr_addr(write_addr),.i_wr_data(write_data),.i_wr_mask(write_mask),
  .i_rd_en(read_enable),.i_rd_addr(read_addr),.o_rd_data(reference_data));
 ia_ps_role_ram #(.p_depth(p_depth),.p_addr_width(p_addr_width)) u_current(
  .clk(clk),.i_access_enable(access_enable),
  .i_a_enable(!ia_owner && ps_read),.i_a_write(ia_owner && ia_write),
  .i_a_addr(ia_owner?ia_write_addr:ps_read_addr),.i_a_data(ia_data),.i_a_mask(ia_mask),.o_a_data(ps_return),
  .i_b_enable(ia_owner && ia_read),.i_b_write(!ia_owner && ps_write),
  .i_b_addr(ia_owner?ia_read_addr:ps_write_addr),.i_b_data(ps_data),.o_b_data(ia_return));
 // 用请求当拍的所有者选择下一拍实际返回，并独立检查同址读写的旧值返回。
 always_ff @(posedge clk)begin
  previous_read<=read_enable;
  previous_owner<=ia_owner;
  previous_read_addr<=read_addr;
  previous_watched_row<=watched_row;
 end
 assign memory_equal=u_reference.mem[watched_row][8*p_byte_index+:8]==
  u_current.memory[watched_row][8*p_byte_index+:8];
 wire [127:0] current_data=previous_owner?ia_return:ps_return;
 assign equivalent=memory_equal && (!previous_read || previous_read_addr!=watched_row ||
  reference_data[8*p_byte_index+:8]==current_data[8*p_byte_index+:8]);
endmodule
'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--depths',type=int,nargs='+',default=[32,128])
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    source_root=args.source_root.resolve()
    wrapper=out/'storage.sv';wrapper.write_text(WRAPPER)
    sources=[wrapper,source_root/'rtl/common/regfile.v',source_root/'rtl/npu/buffers/ia_ps_role_ram.sv']
    hashes={str(path):digest(path)for path in sources}
    records=[]
    for depth in args.depths:
        for byte_index in range(16):
            label=f'd{depth}_b{byte_index}'
            script,log=out/(label+'.ys'),out/(label+'.log')
            script.write_text('read_slang --top storage_transition '+
                shlex.join([f'-Gp_depth={depth}',f'-Gp_byte_index={byte_index}',*map(str,sources)])+'\n'+
                'prep -top storage_transition -flatten\nmemory_share\nmemory_map\nopt -full\n'+
                'techmap\nopt -full\nopt_clean -purge\n'+
                'sat -verify -seq 2 -set-at 1 memory_equal 1 -set-at 1 previous_read 0 '+
                '-set-at 2 watch_stable 1 '+
                '-prove-skip 1 -prove equivalent 1\n')
            with log.open('w')as stream:
                subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                    cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=180)
            assert 'SUCCESS!' in log.read_text()
            records.append(dict(depth=depth,byte_index=byte_index,passed=True,log_sha256=digest(log)))
            print('ROLE_STORAGE_TRANSITION_PASS',label,flush=True)
    assert hashes=={str(path):digest(path)for path in sources}
    report=dict(passed=True,source_sha256=hashes,profiles=records,
        scope='实际 128 位存储数组的每个字节及同步返回，包含同址读写和任意逐周期所有者选择',
        initial_state='各字节分别证明：符号行地址任意且保持不变，第一拍该行对应字节内容相同，其他存储位任意',
        induction='任意行的相同字节经一步任意输入更新后仍相同；读取该行时同步返回相同，因此覆盖全部行和连续访问',
        test_sha256=digest(Path(__file__)))
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
