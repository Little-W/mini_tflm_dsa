#!/usr/bin/env python3
"""Generate the measured partial-sum implementation cost report and figures."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re


def load(path):
    return json.loads(path.read_text())


def implementation(directory):
    run=load(directory/'run.json')
    assert run['passed'] and run['sources_unchanged']
    area=load(directory/'cell_cost.json')
    report=(directory/'npu_top_area.rpt').read_text()
    total=float(re.search(r'Total cell area:\s*([\d.eE+-]+)',report)[1])
    assert abs(area['total_area_um2']-total)<max(1,total*1e-4)
    timing={}
    for line in (directory/'npu_top_summary.rpt').read_text().splitlines():
        key,separator,value=line.partition(':')
        if separator and key in ('target_freq_mhz','clock_period_ns','worst_setup_slack_ns','worst_hold_slack_ns'):
            timing[key]=float(value)
    path=(directory/'npu_top_timing.rpt').read_text()
    start=re.search(r'Startpoint:\s*([^\n]+)',path)
    end=re.search(r'Endpoint:\s*([^\n]+)',path)
    return dict(area=area,timing=timing,source_commit=run['source_commit'],
        source_sha256=run['source_sha256'],parameters=run['parameters'],
        compile_mode=run.get('compile_mode','standard'),
        critical_start=start[1].strip() if start else '',critical_end=end[1].strip() if end else '',
        area_report_sha256=hashlib.sha256((directory/'npu_top_area.rpt').read_bytes()).hexdigest())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-dc',type=Path,required=True)
    parser.add_argument('--compressed-dc',type=Path,required=True)
    parser.add_argument('--measurements',type=Path,required=True)
    parser.add_argument('--methods',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--preview',type=Path)
    parser.add_argument('--equal-total-ram',type=Path)
    args=parser.parse_args()
    raw,compressed=[implementation(p.resolve()) for p in [args.raw_dc,args.compressed_dc]]
    assert raw['parameters']==compressed['parameters']
    assert raw['timing']['target_freq_mhz']==compressed['timing']['target_freq_mhz']
    assert raw['compile_mode']==compressed['compile_mode']
    tests=load(args.measurements)
    assert tests['passed'] and len(tests['datasets'])==10
    ratio=compressed['area']['total_area_um2']/raw['area']['total_area_um2']
    records=[];points=[]
    for case in tests['datasets']:
        a,b,c=[case[k] for k in ['raw_best','compressed_best','compressed_same_workspace']]
        point=dict(kind=case['kind'],dataflow='IS' if case['dataflow'] else 'WS',
            raw=a,compressed=b,same_workspace=c,speedup=a['cycles']/b['cycles'],
            same_workspace_speedup=a['cycles']/c['cycles'],
            throughput_per_area=(a['cycles']/b['cycles'])/ratio,
            encoded_bytes_per_row=16*b['ps_payload_words']/b['ps_committed_rows'])
        points.append(point)
        for name,rows in case['configurations'].items():
            for row in rows:
                assert row['int32_checks']==9216 and row['write_bytes']==9216 and row['ps_committed_rows']==8640
                records.append(dict(kind=case['kind'],dataflow=point['dataflow'],implementation=name,**row))
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    data=dict(raw=raw,compressed=compressed,area_ratio=ratio,points=points,
              search_cases=len(records),int32_checks=sum(x['int32_checks'] for x in records),
              shared_data_bytes=18432,macs_per_case=2359296)
    if args.equal_total_ram:
        equal=load(args.equal_total_ram)
        assert equal['passed'] and len(equal['datasets'])==10
        capacities=equal['shared_data_bytes_by_implementation']
        directories=equal['directory_bytes_by_implementation']
        assert capacities['raw']+directories['raw']==capacities['compressed']+directories['compressed']
        data['equal_total_ram']=equal
    (out/'results.json').write_text(json.dumps(data,indent=2)+'\n')
    fields=['kind','dataflow','implementation','ia_banks','r','w','word_cap','ps_control','cycles',
            'ar_bytes','write_bytes','int32_checks','ps_committed_rows','ps_payload_words','ps_raw_records',
            'ps_blocked_cycles','frame_commands','pressure_events','early_finish_frames']
    with (out/'configurations.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(records)
    text=args.methods.read_text().replace('覆盖最大 256 行','覆盖 256 行')
    text+='\n## 5 综合结果\n\n'
    text+=f'两种实现均使用完整 NPU、相同配置和 `{raw["compile_mode"]}` 综合流程。\n\n'
    text+='| 指标 | 直接 INT32 | 无损压缩 |\n|---|---:|---:|\n'
    for label,key,scale in [('标准单元面积 / mm²','standard_area_um2',1e6),
        ('其中时序单元面积 / mm²','sequential_area_um2',1e6),
        ('其中组合单元面积 / mm²','combinational_area_um2',1e6),
        ('SRAM 宏面积 / mm²','macro_area_um2',1e6),('总单元面积 / mm²','total_area_um2',1e6),
        ('部分和存储标准单元面积 / mm²','ps_standard_area_um2',1e6),
        ('目录宏面积 / mm²','directory_area_um2',1e6),('SRAM 宏物理容量 / KiB','macro_bytes',1024)]:
        text+=f'| {label} | {raw["area"][key]/scale:.4f} | {compressed["area"][key]/scale:.4f} |\n'
    text+=f'\n总单元面积增加 {(ratio-1)*100:.2f}%。压缩实现中的编码器和解码器面积分别为 '
    text+=f'{compressed["area"]["encoder_area_um2"]/1e6:.4f} mm² 和 {compressed["area"]["decoder_area_um2"]/1e6:.4f} mm²。\n\n'
    text+=f'| {raw["timing"]["target_freq_mhz"]:g} MHz 时序指标 / ns | 直接 INT32 | 无损压缩 |\n|---|---:|---:|\n'
    for label,key in [('建立时间余量','worst_setup_slack_ns'),('保持时间余量','worst_hold_slack_ns')]:
        text+=f'| {label} | {raw["timing"][key]:.4f} | {compressed["timing"][key]:.4f} |\n'
    text+='\n面积采用综合网表中的实际叶单元统计；时序采用综合约束和库延迟。\n'
    text+='\n## 6 周期与存储收益\n\n'
    text+='固定工作区列使用直接存储实现的最佳 IA/R/W 配置；容量调度列允许两种实现独立选择合法配置。外部读取包含操作数与量化参数。\n\n'
    text+='| 输入 | 数据流 | RAW32 周期 | 压缩，固定工作区 | 压缩，容量调度 | 加速比 | 平均记录 / B |\n|---|---|---:|---:|---:|---:|---:|\n'
    labels={'zero':'零值','small':'小幅值','outlier':'异常幅值','random':'完整 INT8','wide':'INT16'}
    for p in points:
        text+=f'| {labels[p["kind"]]} | {p["dataflow"]} | {p["raw"]["cycles"]:,} | {p["same_workspace"]["cycles"]:,} | {p["compressed"]["cycles"]:,} | {p["speedup"]:.4f} | {p["encoded_bytes_per_row"]:.2f} |\n'
    text+=f'\n共执行 {len(records)} 个配置，检查 {data["int32_checks"]:,} 个 INT32 输出。所有测试的外部写入均为输出矩阵本身，部分和保留在片上；非最终部分和行数保持为每项 8640 行。\n'
    text+='\n![实现面积与性能](ps_compression_cost/cost.svg)\n\n图 1 实现面积及相同计算量下的周期收益。\n'
    if args.equal_total_ram:
        text+='\n### 6.1 总 SRAM 容量相同的比较\n\n'
        text+='直接存储使用 18 KiB 共享数据 RAM；压缩存储使用 12 KiB 共享数据 RAM 和 6 KiB 目录 RAM。其他 SRAM 配置保持一致。两种实现分别搜索合法工作组和 IA/PS 分配。\n\n'
        text+='| 输入 | 数据流 | RAW32 周期 | 压缩周期 | 加速比 | RAW32 读取 / B | 压缩读取 / B |\n|---|---|---:|---:|---:|---:|---:|\n'
        for case in equal['datasets']:
            a,b=case['raw_best'],case['compressed_best']
            text+=f'| {labels[case["kind"]]} | {"IS" if case["dataflow"] else "WS"} | {a["cycles"]:,} | {b["cycles"]:,} | {a["cycles"]/b["cycles"]:.4f} | {a["ar_bytes"]:,} | {b["ar_bytes"]:,} |\n'
        with (out/'equal_total_ram_configurations.csv').open('w') as stream:
            writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');writer.writeheader()
            for case in equal['datasets']:
                for name,rows in case['configurations'].items():
                    for row in rows:
                        assert row['int32_checks']==9216 and row['write_bytes']==9216 and row['ps_committed_rows']==8640
                        writer.writerow(dict(kind=case['kind'],dataflow='IS' if case['dataflow'] else 'WS',implementation=name,**row))
    text+='\n## 7 设计选择\n\n'
    text+='编码减少的字节数、可驻留输出数和执行周期分别对应存储表示、容量分配和调度效率。固定工作区测量给出编码和反馈延迟的成本；扩大工作区后，输入重读减少与额外 frame 控制共同决定周期变化。\n\n'
    text+='目录的 6 KiB 物理容量需要计入容量预算。若保持整个 NPU 的总 SRAM 字节数固定，应从数据 RAM 中扣除这部分容量，再重新选择 IA/PS 分配。当前性能表固定共享数据 RAM 为 18 KiB，目录容量已在实现成本表中单独列明。\n\n'
    text+='同频时，只有周期加速比超过总单元面积比，单位面积吞吐率才会提高。对部分和分布较宽、输入复用未改变的任务，直接存储可提供更低的控制和反馈成本；压缩适合通过缩短记录扩大有效工作区的任务。\n'
    text+='\n## 8 复现\n\n'
    text+='实现位于 `experiment/no-ps-compression` 和 `optimize/ps-hardware`。分别使用 Git worktree 建立工作目录后，在压缩实现目录执行以下命令。`RAW_ROOT` 指向直接存储源码，`PS_STD_DB` 指向标准单元 TT 库，`MEM_DB_PATH` 指向 SRAM 编译库。\n\n'
    text+='```sh\npython3 scripts/asic/run_ps_synthesis.py --source-root "$RAW_ROOT" --force-raw \\\n  --std-db "$PS_STD_DB" --libs "$MEM_DB_PATH" --out build/ps_cost/raw\npython3 scripts/asic/run_ps_synthesis.py \\\n  --std-db "$PS_STD_DB" --libs "$MEM_DB_PATH" --out build/ps_cost/compressed\npython3 test/ps_compression/compare_hardware.py --raw-root "$RAW_ROOT" \\\n  --out build/ps_cost/performance\n```\n\n'
    text+='[结构化结果](ps_compression_cost/results.json)保存源文件摘要、综合参数、面积和时序；[配置扫描数据](ps_compression_cost/configurations.csv)保存逐配置周期和访问量。\n'
    (out.parent/'ps_compression_cost.md').write_text(text)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'svg.fonttype':'none'})
    figure,axes=plt.subplots(1,2,figsize=(11.5,4.1),layout='constrained')
    bottom=np.zeros(2)
    for key,label,color in [('sequential_area_um2','Sequential logic','#427c9c'),
        ('combinational_area_um2','Combinational logic','#84b09b'),('macro_area_um2','SRAM macros','#c9c9c9')]:
        values=np.array([raw['area'][key],compressed['area'][key]])/1e6
        axes[0].bar(['INT32','Compressed'],values,bottom=bottom,label=label,color=color,width=.5)
        bottom+=values
    axes[0].set_ylabel('Mapped cell area (mm²)');axes[0].legend(frameon=False,fontsize=8)
    axes[0].set_title('(a) Full NPU implementation')
    x=np.arange(len(points));axes[1].bar(x-.18,[p['same_workspace_speedup'] for p in points],.36,label='Same workspace',color='#427c9c')
    axes[1].bar(x+.18,[p['speedup'] for p in points],.36,label='Capacity scheduling',color='#84b09b')
    axes[1].axhline(1,color='#333333',lw=.8)
    axes[1].set_xticks(x,[p['kind']+'\n'+p['dataflow'] for p in points],rotation=45,ha='right')
    axes[1].set_ylabel('INT32 cycles / compressed cycles');axes[1].set_ylim(.85,1.16)
    axes[1].set_title('(b) Equal MAC count and shared data RAM');axes[1].legend(frameon=False,fontsize=8)
    for ax in axes:
        ax.spines[['top','right']].set_visible(False);ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    figure.savefig(out/'cost.svg')
    if args.preview:
        args.preview.parent.mkdir(parents=True,exist_ok=True)
        figure.savefig(args.preview,dpi=150)
    print('PS_COST_REPORT_PASS',out.parent/'ps_compression_cost.md')


if __name__=='__main__':
    main()
