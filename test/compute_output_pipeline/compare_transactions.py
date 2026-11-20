#!/usr/bin/env python3
"""比较完整 NPU 事务及其参考数据，分别记录任务执行周期。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def suites(report):
    functional=load(report['runs']['functional']['npu_report'])
    assert functional['passed']
    result=[('functional/'+item['name'],item) for item in functional['cases']]
    result += [(name,report['runs'][name]['suite']) for name in ('capacity','output')]
    result.append(('packed',report['runs']['packed']))
    for _,suite in result:
        assert suite['passed'] and suite['returncode']==0
        assert len(suite['tasks'])==len(suite['measurements'])
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-report',type=Path,required=True)
    parser.add_argument('--current-report',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    old,new=load(args.reference_report),load(args.current_report)
    assert old['passed'] and new['passed']
    old_suites,new_suites=suites(old),suites(new)
    assert [name for name,_ in old_suites]==[name for name,_ in new_suites]
    checked_fields=('task','conv','dataflow','bypass','error','capacity_injected',
                    'ia_banks','ia_bytes','ps_bytes','r','w','ps_control')
    rows=[]
    for (name,before),(_,after) in zip(old_suites,new_suites):
        assert len(before['tasks'])==len(after['tasks'])
        for index,(a,b,old_task,new_task) in enumerate(zip(
                before['measurements'],after['measurements'],before['tasks'],after['tasks'])):
            assert Path(old_task).name==Path(new_task).name
            inputs={path.name:digest(path) for path in Path(old_task).glob('*.mem')}
            current={path.name:digest(path) for path in Path(new_task).glob('*.mem')}
            assert inputs and inputs==current,(name,index)
            assert {key:a[key] for key in checked_fields}=={key:b[key] for key in checked_fields},(name,index)
            if b['error']==0:
                assert a['int32_checks']==b['int32_checks'] and a['write_bytes']==b['write_bytes'],(name,index)
            changes={key:{'reference':a[key],'current':b[key]}
                     for key in sorted(set(a)&set(b)) if a[key]!=b[key]}
            rows.append(dict(suite=name,task=Path(new_task).name,index=index,
                             error=b['error'],int32_checks=b['int32_checks'],write_bytes=b['write_bytes'],
                             reference_cycles=a['cycles'],current_cycles=b['cycles'],
                             cycle_difference=b['cycles']-a['cycles'],measurements_changed=changes,
                             task_memory_sha256=current))
    old_build,new_build=load(old['simulator_manifest']),load(new['simulator_manifest'])
    parameters=('size','bus_width','shared_bank_bytes','shared_bank_count','cache_sets',
                'cache_ways','cache_line_bytes','cache_data_bytes','cache_policy','ps_compress',
                'pool_bytes','force_raw','lint_only','ps_frame_count')
    assert {key:old_build[key] for key in parameters}=={key:new_build[key] for key in parameters}
    assert new_build['sources_unchanged_during_build'] and new_build['returncode']==0
    report=dict(passed=True,tasks=len(rows),
                reference_report=str(args.reference_report.resolve()),
                current_report=str(args.current_report.resolve()),
                reports_sha256={'reference':digest(args.reference_report),'current':digest(args.current_report)},
                reference_binary_sha256=old_build['binary_sha256'],
                current_binary_sha256=new_build['binary_sha256'],
                build_parameters={key:new_build[key] for key in parameters},
                reference_cycles=sum(row['reference_cycles'] for row in rows),
                current_cycles=sum(row['current_cycles'] for row in rows),
                cycle_difference=sum(row['cycle_difference'] for row in rows),
                minimum_task_cycle_difference=min(row['cycle_difference'] for row in rows),
                maximum_task_cycle_difference=max(row['cycle_difference'] for row in rows),
                int32_checks=sum(row['int32_checks'] for row in rows),
                functional_fields_compared=list(checked_fields),
                scope='每项事务均检查目的内存和 INT32 行序列；成功事务的输出数量相同，记录周期变化',
                cases=rows)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({key:report[key] for key in ('passed','tasks','reference_cycles','current_cycles',
                                               'cycle_difference','int32_checks')}))


if __name__=='__main__':
    main()
