#!/usr/bin/env python3
"""证明 FIFO 全部周期行为、数据存储端口和并行行数保存关系。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
SOURCE=Path('rtl/npu/writeback/vec_s8_to_fifo_full.sv')
REFERENCE='8fe8b96991259ef9c7f0e18ad9fc326a1353fa8e'
PROFILES=((16,1,64,1),(16,3,64,1),(16,8,32,1),(16,16,64,1),
          (16,32,32,1),(16,32,64,1),(16,64,64,1),(16,32,64,0),(8,8,32,0))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def observed_source(source):
    marker='\n);'
    first=source.index(marker)
    prefix=source[:first]
    prefix,count=re.subn(r'(\bfifo_full_flag)(\s*/\*[^*]*\*/)?\s*$',r'\1,\2',prefix)
    assert count==1
    ports='''
    input wire [BUS_WIDTH/8-1:0][VLEN*8-1:0] formal_ram_read_data,
    output wire [BUS_WIDTH/8-1:0][VLEN*8-1:0] formal_ram_write_data,
    output wire [BUS_WIDTH/8-1:0][31:0] formal_ram_write_addr, formal_ram_read_addr,
    output wire [BUS_WIDTH/8-1:0] formal_ram_write_enable, formal_ram_read_enable,
    output wire [BANKS*$clog2(VLEN+1)-1:0] formal_bank_counts, formal_parallel_counts
'''
    text=prefix+ports+source[first:]
    replacement='''assign fifo_ram_o_rd_data = $bits(fifo_ram_o_rd_data)'(formal_ram_read_data[ram_bank]);
        assign formal_ram_write_data[ram_bank] = (VLEN*8)'(fifo_ram_i_wr_data);
        assign formal_ram_write_addr[ram_bank] = 32'(fifo_ram_i_wr_addr);
        assign formal_ram_read_addr[ram_bank] = 32'(fifo_ram_i_rd_addr);
        assign formal_ram_write_enable[ram_bank] = fifo_ram_i_wr_en;
        assign formal_ram_read_enable[ram_bank] = fifo_ram_i_rd_en;'''
    text,count=re.subn(r'vec_s8_fifo_row_ram\s*#\(.*?\)\s*u_fifo_ram\s*\(.*?\);',
                       replacement,text,flags=re.S)
    assert count==2
    parallel=('g_parallel_co_row_match.u_row_match.count_q[bank]'
              if 'g_parallel_co_row_match' in source else 'g_count_memory.u_bank_count.mem[bank]')
    relation=f'''
  for (genvar bank=0;bank<BANKS;bank++) begin : g_formal_count
    if(p_count_storage) begin : g_memory
      assign formal_bank_counts[bank*COUNT_WIDTH+:COUNT_WIDTH] =
          bank_ready[bank] ? g_count_memory.u_bank_count.mem[bank] : '0;
      assign formal_parallel_counts[bank*COUNT_WIDTH+:COUNT_WIDTH] =
          bank_ready[bank] ? {parallel} : '0;
    end else begin : g_registers
      assign formal_bank_counts[bank*COUNT_WIDTH+:COUNT_WIDTH] = g_count_registers.bank_count[bank];
      assign formal_parallel_counts[bank*COUNT_WIDTH+:COUNT_WIDTH] = g_count_registers.bank_count[bank];
    end
  end
'''
    assert text.count('endmodule')==1
    return text.replace('endmodule',relation+'\nendmodule')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference',default=REFERENCE)
    parser.add_argument('--profile',help='只运行指定的 v16_n32_b64_c1 配置')
    parser.add_argument('--mode',choices=('generic','fpga','all'),default='all')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    current=(ROOT/SOURCE).read_text()
    reference=subprocess.check_output(['git','show',args.reference+':'+str(SOURCE)],cwd=ROOT,text=True)
    resolver=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources={}
    for label,original in [('reference',reference),('current',current)]:
        path=out/(label+'.sv');path.write_text(observed_source(original))
        sources[label]=resolver([path],ROOT)
    hashes={str(p):digest(p) for paths in sources.values() for p in paths}
    hashes[str(ROOT/SOURCE)]=digest(ROOT/SOURCE)
    runs=[]
    modes={'generic':['-USYNTHESIS','-UXILINX_FPGA'],
           'fpga':['-DSYNTHESIS=1','-DXILINX_FPGA=1']}
    for mode,flags in modes.items():
        if args.mode!='all' and mode!=args.mode: continue
        for vlen,banks,bus,cyclic in PROFILES:
            profile=f'v{vlen}_n{banks}_b{bus}_c{cyclic}'
            if args.profile and args.profile!=profile: continue
            name=mode+'_'+profile;commands=[]
            options=[f'-GVLEN={vlen}',f'-GBANKS={banks}',f'-GBUS_WIDTH={bus}',
                     f'-Gp_cyclic_storage={cyclic}','-Gp_precomputed_watermark=1']
            for label,paths in sources.items():
                commands += ['read_slang --top vec_s8_to_fifo_full '+shlex.join(flags+options+list(map(str,paths))),
                    'setattr -mod -unset keep_hierarchy','setattr -unset keep_hierarchy','setattr -unset keep',
                    'prep -top vec_s8_to_fifo_full -flatten','async2sync','memory_map','opt -full',
                    'rename vec_s8_to_fifo_full '+label,'design -stash '+label]
            commands += ['design -copy-from reference -as reference reference',
                         'design -copy-from current -as current current',
                         'expose -dff -shared reference/w:* current/w:* '
                         'reference/w:g_count_memory.* %d current/w:g_count_memory.* %d',
                         'miter -equiv -make_outcmp -flatten reference current miter',
                         'hierarchy -top miter','opt_clean',
                         'sat -seq 2 -tempinduct -maxsteps 7 -set-at 1 in_rst_n 0 -prove trigger 0 -verify']
            script=out/(name+'.ys');log=out/(name+'.log');script.write_text('\n'.join(commands)+'\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],
                    cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=600)
            text=log.read_text();assert 'Induction step proven: SUCCESS!' in text
            steps=re.findall(r'\[induction step (\d+)\]',text)
            row=dict(mode=mode,vlen=vlen,banks=banks,bus_width=bus,cyclic_storage=cyclic,
                     passed=True,induction_steps=int(steps[-1]),log_sha256=digest(log))
            runs.append(row);print(json.dumps(row),flush=True)
    assert runs
    assert all(digest(p)==h for p,h in hashes.items())
    report=dict(passed=True,reference_commit=args.reference,source_sha256=hashes,
                reference_sha256=hashlib.sha256(reference.encode()).hexdigest(),
                initial_reset_cycle=1,subsequent_reset_unconstrained=True,
                functional_inputs_constrained=False,data_ram_inputs_constrained=False,
                all_common_state_and_public_ports_compared=True,parallel_count_relation_proven=True,
                runner_sha256=digest(__file__),runs=runs)
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    main()
