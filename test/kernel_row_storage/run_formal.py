#!/usr/bin/env python3
"""按物理槽位、矩阵行和矩阵列统一存储名字后证明权重缓存等价。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
RTL = Path('rtl/npu/loaders/kernel_loader_buffer.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--reference-root',type=Path,required=True)
    parser.add_argument('--profiles',nargs='+',default=['4:8'])
    parser.add_argument('--seq',type=int,default=4)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    hashes={};sources={}
    for label,root in [('reference',args.reference_root.resolve()),('current',args.source_root.resolve())]:
        sources[label]=[]
        for relative in [RTL,Path('rtl/common/regfile.v')]:
            path=root/relative;hashes[str(path)]=digest(path)
            copy=out/'inputs'/label/relative;copy.parent.mkdir(parents=True,exist_ok=True);copy.write_bytes(path.read_bytes())
            sources[label].append(copy)
    records=[]
    for profile in args.profiles:
        size,width=map(int,profile.split(':'));commands=[]
        for label in ('reference','current'):
            commands += [f'read_slang -D SYNTHESIS=1 --top kernel_loader_buffer -GSIZE={size} -GDATA_WIDTH={width} '+
                         ' '.join(map(str,sources[label])),
                         'prep -top kernel_loader_buffer -flatten','memory_map','async2sync','opt_clean','cd kernel_loader_buffer']
            for slot in range(3):
                for row in range(size):
                    for column in range(size):
                        name=f'storage_slot_{slot}_row_{row}_column_{column}'
                        if label=='reference':
                            old=f'g_column_ram[{column}].u_column.mem[{slot*size+row}]'
                        elif size>1 and (size&(size-1))==0:
                            old=f'g_row_storage.g_row[{row}].mem[{slot*size+column}]'
                        else:
                            old=f'g_column_storage.g_column_ram[{column}].u_column.mem[{slot*size+row}]'
                        commands.append(f'rename \\{old} \\{name}')
            commands += ['cd ..',f'rename kernel_loader_buffer {label}',f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current equivalent','hierarchy -top equivalent',
                     'equiv_simple -short -seq 1','opt_clean',f'equiv_induct -seq {args.seq}',
                     'equiv_status -assert']
        stem=profile.replace(':','_');ys=out/(stem+'.ys');log=out/(stem+'.log')
        ys.write_text('\n'.join(commands)+'\n')
        with log.open('w')as stream:
            result=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(ys)],
                                  stdout=stream,stderr=subprocess.STDOUT,timeout=1800)
        match=re.search(r'Of those cells (\d+) are proven and (\d+) are unproven',log.read_text())
        if result.returncode or match is None or int(match[2]):raise RuntimeError(str(log))
        row={'SIZE':size,'DATA_WIDTH':width,'passed':True,'equivalent_bits':int(match[1]),
             'matrix_storage_bits':3*size*size*width,'script_sha256':digest(ys),'log_sha256':digest(log)}
        records.append(row);print(json.dumps(row),flush=True)
    if any(digest(Path(path))!=sha for path,sha in hashes.items()):raise RuntimeError('验证期间源文件发生变化')
    report={'passed':True,'source_sha256':hashes,'inputs_constrained':False,'profiles':records,
            'equivalent_bits':sum(x['equivalent_bits']for x in records)}
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
