#!/usr/bin/env python3
"""证明全部矩阵存储，再按数据位分组证明所有权重输出通道。"""
import argparse,fcntl,hashlib,json,re,shlex,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
RTL=Path('rtl/npu/loaders/kernel_loader_buffer.sv')

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def prepare(config):
    from pyosys import libyosys as ys
    size,width=config['SIZE'],config['DATA_WIDTH'];out=Path(config['out']);design=ys.Design()
    commands=[];renamed=[]
    def run(cmd):
        commands.append(cmd);ys.run_pass(cmd,design)
    for label in ('reference','current'):
        src=out/'inputs'/label
        files=[src/RTL,src/'rtl/common/regfile.v']
        definitions=' '.join('-D'+value for value in config.get('defines',[]))
        run(f'read_slang -D SYNTHESIS=1 {definitions} --top kernel_loader_buffer -GSIZE={size} -GDATA_WIDTH={width} '+shlex.join(map(str,files)))
        run('prep -top kernel_loader_buffer -flatten; memory_map; async2sync; opt_clean')
        module=design.module('\\kernel_loader_buffer')
        for slot in range(3):
            for row in range(size):
                for column in range(size):
                    layout=config.get(label+'_layout','legacy_column' if label=='reference' else 'parameter')
                    if layout=='legacy_column':old=f'g_column_ram[{column}].u_column.mem[{slot*size+row}]'
                    elif layout=='row' or (layout=='parameter' and size>1 and size&(size-1)==0):
                        old=f'g_row_storage.g_row[{row}].mem[{slot*size+column}]'
                    else:old=f'g_column_storage.g_column_ram[{column}].u_column.mem[{slot*size+row}]'
                    name=f'storage_slot_{slot}_row_{row}_column_{column}'
                    wire=module.wire('\\'+old)
                    if wire is None or wire.width!=width:raise RuntimeError(f'存储目标缺失或宽度不符：{label} {old}')
                    module.rename(wire,'\\'+name)
                    renamed.append({'design':label,'source':old,'canonical':name,'width':width})
        run(f'rename kernel_loader_buffer {label}; design -stash {label}')
    run('design -copy-from reference -as reference reference; design -copy-from current -as current current')
    run('equiv_make reference current equivalent; hierarchy -top equivalent')
    run('select -set weight_outputs equivalent/w:weight_out %ci1 equivalent/t:$equiv %i')
    run(f'select -assert-count {size*width} @weight_outputs')
    run('equiv_simple -short -seq 1 equivalent/t:$equiv @weight_outputs %d')
    run('equiv_status -assert equivalent/t:$equiv @weight_outputs %d')
    run('select -clear; opt_clean; equiv_status')
    run('write_rtlil '+shlex.quote(str(out/'state_proven.il')))
    run('write_json '+shlex.quote(str(out/'state_proven.json')))
    (out/'prepare_operations.json').write_text(json.dumps({'yosys_commands':commands,'memory_renames':renamed},indent=2)+'\n')

def locked_run(command,log,lock_file,timeout):
    log.parent.mkdir(parents=True,exist_ok=True)
    lock_file.parent.mkdir(parents=True,exist_ok=True)
    with lock_file.open('a+')as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
        try:
            with log.open('w')as stream:
                result=subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,timeout=timeout)
            if result.returncode:raise RuntimeError(f'{log}: returncode={result.returncode}')
        finally:fcntl.flock(lock.fileno(),fcntl.LOCK_UN)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--worker-prepare',type=Path)
    p.add_argument('--source-root',type=Path);p.add_argument('--reference-root',type=Path)
    p.add_argument('--size',type=int,default=32);p.add_argument('--width',type=int,default=16)
    p.add_argument('--define',action='append',default=[])
    p.add_argument('--reference-layout',choices=['legacy_column','parameter','column','row'],default='legacy_column')
    p.add_argument('--source-layout',choices=['parameter','column','row'],default='parameter')
    p.add_argument('--out',type=Path);p.add_argument('--lock-file',type=Path,default=ROOT/'build/kernel_row_storage/formal.lock')
    p.add_argument('--prepare-timeout',type=int,default=420);p.add_argument('--group-timeout',type=int,default=90)
    p.add_argument('--seq',type=int,default=4);p.add_argument('--prepare-only',action='store_true');p.add_argument('--groups',nargs='+',type=int)
    p.add_argument('--pause-file',type=Path,help='文件存在时在下一组开始前保存状态并退出')
    a=p.parse_args()
    if a.worker_prepare:prepare(json.loads(a.worker_prepare.read_text()));return
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    config={'SIZE':a.size,'DATA_WIDTH':a.width,'out':str(out),'defines':a.define,
            'reference_layout':a.reference_layout,'current_layout':a.source_layout};cfg=out/'config.json'
    if not cfg.exists():
        manifest={}
        for label,source_root in [('reference',a.reference_root.resolve()),('current',a.source_root.resolve())]:
            for relative in [RTL,Path('rtl/common/regfile.v')]:
                source=source_root/relative;target=out/'inputs'/label/relative
                target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(source.read_bytes());manifest[str(source)]=digest(source)
        config['source_sha256']=manifest;config['runner_sha256']=digest(Path(__file__).resolve());cfg.write_text(json.dumps(config,indent=2)+'\n')
    else:
        config=json.loads(cfg.read_text())
        if config['SIZE']!=a.size or config['DATA_WIDTH']!=a.width:raise RuntimeError('参数与保存点不符')
        if config.get('defines',[])!=a.define or config.get('reference_layout','legacy_column')!=a.reference_layout or config.get('current_layout','parameter')!=a.source_layout:
            raise RuntimeError('综合定义或存储布局与保存点不符')
        for label,source_root in [('reference',a.reference_root.resolve()),('current',a.source_root.resolve())]:
            for relative in [RTL,Path('rtl/common/regfile.v')]:
                source=source_root/relative;copied=out/'inputs'/label/relative
                expected=config['source_sha256'].get(str(source))
                if expected is None or digest(source)!=expected or digest(copied)!=expected:
                    raise RuntimeError('源文件与保存点不符：'+str(source))
    prepare_report=out/'prepare_summary.json'
    if not prepare_report.exists():
        locked_run([sys.executable,str(Path(__file__).resolve()),'--worker-prepare',str(cfg)],out/'prepare.log',a.lock_file,a.prepare_timeout)
        state=json.loads((out/'state_proven.json').read_text())['modules']['equivalent'];counts={'proven':0,'unproven':0}
        for cell in state['cells'].values():
            if cell['type']=='$equiv':counts['proven'if cell['connections']['A']==cell['connections']['B']else'unproven']+=1
        if counts['unproven']!=a.size*a.width:raise RuntimeError('未证明目标集合与权重输出宽度不符')
        report=dict(passed=True,SIZE=a.size,DATA_WIDTH=a.width,matrix_storage_bits=3*a.size*a.size*a.width,comparison_bits=counts,all_storage_locations_matched=True,inputs_constrained=False,
                    artifacts={n:digest(out/n)for n in ['state_proven.il','state_proven.json','prepare_operations.json','prepare.log']})
        prepare_report.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'prepare':report}),flush=True)
    prepared=json.loads(prepare_report.read_text())
    for name in ['state_proven.il','state_proven.json','prepare_operations.json']:
        if digest(out/name)!=prepared['artifacts'][name]:raise RuntimeError('中间形式文件散列不符：'+name)
    if a.prepare_only:return
    module=json.loads((out/'state_proven.json').read_text())['modules']['equivalent'];output_bits=module['netnames']['weight_out']['bits'];cells_by_bit={}
    for name,cell in module['cells'].items():
        if cell['type']=='$equiv' and cell['connections']['A']!=cell['connections']['B']:
            for bit in cell['connections']['Y']:
                if bit in cells_by_bit:raise RuntimeError('输出比较目标重复')
                cells_by_bit[bit]=name
    if len(output_bits)!=a.size*a.width or set(output_bits)!=set(cells_by_bit):raise RuntimeError('权重输出目标未完整对应')
    groups=a.groups if a.groups is not None else range(a.width)
    for bit in groups:
        if a.pause_file is not None and a.pause_file.exists():
            print(json.dumps({'paused':True,'next_data_bit':bit}),flush=True);return
        if not 0<=bit<a.width:raise RuntimeError('数据位编号超出范围')
        indices=list(range(bit,a.size*a.width,a.width));selected=[cells_by_bit[output_bits[i]]for i in indices]
        result_path=out/f'group_{bit}.json'
        if result_path.exists():
            stored=json.loads(result_path.read_text())
            if stored['output_indices']!=indices or stored['comparison_cells']!=selected or stored['proven_bits']!=a.size:
                raise RuntimeError('已有输出分组与目标不符')
            for suffix in ['ys','log']:
                key='script_sha256'if suffix=='ys'else'log_sha256'
                if digest(out/f'group_{bit}.{suffix}')!=stored[key]:raise RuntimeError('分组证明文件散列不符')
            continue
        other=[name for name in cells_by_bit.values()if name not in selected]
        commands=['read_rtlil '+shlex.quote(str(out/'state_proven.il')),
                  'select -set group '+' '.join('equivalent/c:'+name for name in selected),
                  f'select -assert-count {a.size} @group',
                  'delete -output equivalent/w:weight_out',
                  'setattr -set keep 1 @group',
                  'delete '+' '.join('equivalent/c:'+name for name in other),
                  'select -clear','techmap','opt_clean',f'equiv_induct -seq {a.seq}',
                  'equiv_status -assert @group']
        script=out/f'group_{bit}.ys';script.write_text('\n'.join(commands)+'\n');log=out/f'group_{bit}.log'
        locked_run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],log,a.lock_file,a.group_timeout)
        match=re.search(r'Of those cells (\d+) are proven and (\d+) are unproven',log.read_text())
        if match is None or int(match[1])!=a.size or int(match[2])!=0:raise RuntimeError(str(log))
        row=dict(passed=True,data_bit=bit,output_indices=indices,comparison_cells=selected,proven_bits=a.size,script_sha256=digest(script),log_sha256=digest(log))
        result_path.write_text(json.dumps(row,indent=2)+'\n');print(json.dumps({'group':bit,'proven_bits':a.size}),flush=True)
        time.sleep(0.5)
    records=[]
    for bit in range(a.width):
        f=out/f'group_{bit}.json'
        if not f.exists():return
        records.append(json.loads(f.read_text()))
    covered=[i for r in records for i in r['output_indices']]
    if sorted(covered)!=list(range(a.size*a.width)):raise RuntimeError('输出覆盖范围不完整或重复')
    prep=json.loads(prepare_report.read_text())
    if any(digest(Path(p))!=h for p,h in config['source_sha256'].items()):raise RuntimeError('验证期间源文件发生变化')
    summary=dict(runner_sha256=digest(Path(__file__).resolve()),passed=True,SIZE=a.size,DATA_WIDTH=a.width,source_sha256=config['source_sha256'],matrix_storage_bits=prep['matrix_storage_bits'],equivalent_bits=sum(prep['comparison_bits'].values()),inputs_constrained=False,all_state_and_outputs=True,proof_partition='每个数据位包含全部输出通道，各组覆盖互不重复且完整。',groups=records,prepare_report_sha256=digest(prepare_report))
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps({'passed':True,'equivalent_bits':summary['equivalent_bits']}),flush=True)
if __name__=='__main__':main()
