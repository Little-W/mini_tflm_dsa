#!/usr/bin/env python3
"""证明 IA 双端口行地址关系及专用存储模式的有效访问等价。"""
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


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execute(script, log):
    with log.open('w') as stream:
        subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),
            '--worker',str(script)],stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=300)
    text=log.read_text()
    if 'SUCCESS!' not in text:
        raise RuntimeError(f'形式检查未完成：{log}')
    steps=[int(n) for n in re.findall(r'\[induction step (\d+)\]',text)]
    return {'passed':True,'induction_depth':max(steps) if steps else None,
            'log_sha256':digest(log),'script_sha256':digest(script)}


def input_wrapper(source, module, instance, parameters, expression):
    """保留生产参数和全部输入，观察指定的实际层次表达式。"""
    start=source.index('module '+module+' #(')
    end=source.index(') (',start)
    header=source[start:end].replace('module '+module,'module property_top',1)
    ports=source[end:source.index('\n);',end)]
    inputs=[];names=[]
    for line in ports.splitlines():
        if not line.strip().startswith('input '):
            continue
        code,_,comment=line.partition('/*')
        code=code.partition('//')[0].strip().rstrip(',').strip()
        code=re.split(r'(?<![<>=!])=(?!=)',code,maxsplit=1)[0].strip()
        last=code.split()[-1]
        name=code.split()[-2] if last.startswith('[') else last
        names.append(name)
        inputs.append('    '+code+', // '+(comment.split('*/')[0].strip() or '任意外部输入'))
    return (header+') (\n'+'\n'.join(inputs)+'''
    output logic equivalent // 指定的端口性质成立
);
'''+f'    {module} #({parameters}) {instance}(\n'+',\n'.join(
        f'        .{name}({name})' for name in names)+
        '\n    );\n    assign equivalent = '+expression+';\nendmodule\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference',default='2551bb91')
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    resolve=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    paths=['rtl/npu/loaders/ia_loader_cache_mgr.sv',
           'rtl/npu/buffers/vector_shared_store.sv',
           'rtl/npu/buffers/ia_ps_channel_ram.sv',
           'rtl/npu/top/npu_task_configuration.sv']
    source_hashes={name:digest(ROOT/name) for name in paths}
    results={'passed':False,'source_sha256':source_hashes,'source_properties':[],
             'memory_access_equivalence':[]}
    cache=ROOT/paths[0]
    parameters=', '.join(f'.{name}({name})' for name in (
        'SIZE','DATA_WIDTH','BUS_WIDTH','DMA_LANES','REG_WIDTH','CACHE_BLOCKS',
        'COMPACT_S8','RAM_WORD_ADDR_WIDTH','p_compact_offset_width','p_dma_source_layout',
        'p_shared_write_stage','p_precomputed_slot_mask','p_indexed_slot_rows'))
    expression='''(!u_cache.ram_port_rd_en[1] || u_cache.ram_port_rd_addr[1][0]) &&
        (!u_cache.ram_port_wr_en[1] || u_cache.ram_port_wr_addr[1][0])'''
    model=out/'cache_property.sv'
    model.write_text(input_wrapper(cache.read_text(),'ia_loader_cache_mgr','u_cache',parameters,expression))
    sources=resolve([model],ROOT)
    profiles=[dict(BUS_WIDTH=32,CACHE_BLOCKS=4,COMPACT_S8=1,p_dma_source_layout=0,p_shared_write_stage=0),
              dict(BUS_WIDTH=64,CACHE_BLOCKS=32,COMPACT_S8=1,p_dma_source_layout=1,p_shared_write_stage=1),
              dict(BUS_WIDTH=64,CACHE_BLOCKS=32,COMPACT_S8=0,p_dma_source_layout=1,p_shared_write_stage=1)]
    for index,parameters in enumerate(profiles):
        script,log=out/f'cache{index}.ys',out/f'cache{index}.log'
        script.write_text('read_slang --top property_top -DSYNTHESIS=1 '+
            ' '.join(f'-G{k}={v}' for k,v in parameters.items())+' '+shlex.join(map(str,sources))+
            '\nprep -top property_top -flatten\nmemory_map\nasync2sync\nsetattr -unset keep\nopt_clean -purge\n'
            'sat -verify -prove equivalent 1 -tempinduct -seq 2 -set-init-zero -set-at 1 rst_n 0\n')
        result=execute(script,log)|{'module':'ia_loader_cache_mgr','parameters':parameters,
            'input_constraints':None,'property':'第二端口有效读写请求的地址最低位为一'}
        results['source_properties'].append(result)
        print(json.dumps(result,ensure_ascii=False),flush=True)
    vector=ROOT/paths[1]
    parameters=', '.join(f'.{name}({name})' for name in
        ('p_bank_bytes','p_total_bytes','p_addr_width','p_bank_count_width','p_fixed_ps_channels'))
    model=out/'vector_property.sv'
    model.write_text(input_wrapper(vector.read_text(),'vector_shared_store','u_vector',parameters,
        "!u_vector.o_ia_read_en[1] && !u_vector.o_ia_write_en[1]"))
    script,log=out/'vector.ys',out/'vector.log'
    script.write_text('read_slang --top property_top '+shlex.join(map(str,resolve([model],ROOT)))+
        '\nprep -top property_top -flatten\nasync2sync\nopt_clean -purge\n'
        'sat -verify -prove equivalent 1 -seq 1\n')
    results['source_properties'].append(execute(script,log)|{'module':'vector_shared_store',
        'input_constraints':None,'property':'向量任务不使用第二个 IA 端口'})
    configuration=(ROOT/paths[3]).read_text()
    statement=re.search(r'assign ps_capacity_config_invalid_calc = \(p_size == 16\).*?;',
                        configuration,re.S)[0]
    model=out/'configuration_property.sv'
    model.write_text('''// 检查生产容量条件对宽格式任务的分配要求。
module property_top(
    input logic [31:0] active_ps_pool_bytes, // 已分配部分和空间
    input logic [31:0] o_shared_ia_banks_q, // 输入数据物理块数
    input logic [31:0] o_active_ps_bank_count, // 部分和物理块数
    input logic [2:0] ps_config_word_cap, // 部分和行最大字数
    input logic compact, // 输入数据采用紧凑格式
    input logic o_shared_allocation_invalid, // 存储分配格式错误
    input logic ps_cross_k_required, // 需要跨归约分块保留部分和
    input logic ps_admission_bank_capacity_fits, // 部分和行预留量足够
    input logic o_use_frame_commands_s2, // 使用逐帧命令
    input logic ps_long_capacity_fits, // 普通命令容量足够
    output logic equivalent // 合法宽格式配置至少分配两块输入存储
);
    localparam int p_size=16,p_shared_ram_enabled=1;
    typedef struct packed {logic compact;} configuration_t;
    configuration_t configuration;
    logic ps_capacity_config_invalid_calc;
    assign configuration.compact=compact;
'''+statement+'''
    assign equivalent=ps_capacity_config_invalid_calc || compact || o_shared_ia_banks_q>=2;
endmodule
''')
    script,log=out/'configuration.ys',out/'configuration.log'
    script.write_text(f'read_slang --top property_top {model}\nprep -top property_top -flatten\n'
                      'sat -verify -prove equivalent 1\n')
    results['source_properties'].append(execute(script,log)|{'module':'npu_task_configuration',
        'input_constraints':None,'property':'容量检查通过的宽格式配置至少分配两块 IA 存储'})
    helper=runpy.run_path(str(ROOT/'test/shared_ram_access_depth/run_formal.py'))
    reference=subprocess.check_output(['git','show',args.reference+':'+paths[2]],cwd=ROOT,text=True)
    text=helper['miter'](reference,(ROOT/paths[2]).read_text())
    for port,count in [('i_ia_read_en',2),('i_ia_write_en',2),('i_ps_read_en',4),('i_ps_write_en',4)]:
        text=text.replace(f'.{port}({port} & {{{count}{{i_access_enable}}}})',f'.{port}({port})')
    pos=text.index('channel_reference #(')
    text=text[:pos]+text[pos:].replace('.clk(clk), .rst_n(rst_n), .i_cfg_valid(i_cfg_valid),',
        '.clk(clk), .rst_n(rst_n), .i_access_enable(i_access_enable), .i_cfg_valid(i_cfg_valid),',1)
    text=text.replace('  channel_reference #(',
        '  channel_reference #(.p_ia_nonempty_writes(1\'b1), ',1)
    text=text.replace('  channel_current #(',
        '  channel_current #(.p_ia_nonempty_writes(1\'b1), .p_paired_ia_ports(1\'b1), ',1)
    marker='  assign equivalent = reference_fault == current_fault &&'
    text=text.replace(marker,'''  // 物理块选择条件由生产地址性质、配置检查和整机接口断言共同检查。
  wire paired_access_legal = !u_reference.memory_access_enabled ||
      ((!i_ia_read_en[1] || (u_reference.ia_banks_q==2 && i_ia_read_addr[1][0])) &&
       (!i_ia_write_en[1] || (u_reference.ia_banks_q==2 && i_ia_write_addr[1][0])));
  always_comb assume(paired_access_legal);
  logic paired_read_seen_q;
  always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) paired_read_seen_q<=1'b0;
      else if (u_reference.memory_access_enabled && i_ia_read_en[1]) paired_read_seen_q<=1'b1;
  end
  assign equivalent = (!paired_read_seen_q || u_reference.ia_return_bank_q[1]==1) &&
      (!u_reference.configured_q || u_reference.ia_banks_q==1 || u_reference.ia_banks_q==2) &&
      reference_fault == current_fault &&''')
    model=out/'access_property.sv';model.write_text(text)
    for bank_bytes,banks,stage in [(2048,6,0),(2048,6,1),(8192,7,0),(8192,7,1)]:
        label=f'b{bank_bytes}_n{banks}_s{stage}'
        script,log=out/(label+'.ys'),out/(label+'.log')
        script.write_text(f'read_slang --top access_miter -Gp_bank_bytes={bank_bytes} '
            f'-Gp_total_bytes={bank_bytes*banks} -Gp_shared_write_stage={stage} {model}\n'
            'prep -top access_miter -flatten\nasync2sync\nopt_clean\n'
            'sat -verify -set-assumes -prove equivalent 1 -tempinduct -seq 2 '
            '-set-init-zero -set-at 1 rst_n 0\n')
        result=execute(script,log)|{'bank_bytes':bank_bytes,'banks':banks,'shared_write_stage':stage}
        results['memory_access_equivalence'].append(result)
        print(json.dumps(result),flush=True)
    results['specialized_input_condition']='有效物理第二端口访问使用两块 IA 配置且地址最低位为一；其他输入自由'
    results['specialized_scope']='全部存储命令、全部配置与返回选择状态、错误输出；首次有效第二端口读取后，其返回选择固定为物理块一'
    results['reference']=args.reference
    if source_hashes!={name:digest(ROOT/name) for name in paths}:
        raise RuntimeError('证明期间生产源码发生变化')
    results['passed']=True
    (out/'summary.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    main()
