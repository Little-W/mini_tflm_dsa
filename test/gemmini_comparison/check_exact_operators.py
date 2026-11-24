#!/usr/bin/env python3
"""逐字节比较 NPU 与 NVDLA 的共同任务输出，并检查实际访存计时。"""
from pathlib import Path
import argparse
import json
import hashlib
import sys
import shutil

from check_repository_operators import require_same_resources, verify_reference_sources


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('repo','run','public','out'):
        parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--old-fast',type=Path)
    parser.add_argument('--old-default',type=Path)
    parser.add_argument('--reference',type=Path)
    args=parser.parse_args()
    sys.path.insert(0,str(args.repo/'test/gemmini_comparison'))
    from compare_fair_operators import memory_segment,records
    run=args.run.resolve();out=args.out.resolve();out.mkdir(exist_ok=True,parents=True)
    nvdla=json.loads(args.public.read_text());public={r['case']:r for r in nvdla['results']}
    summary=json.loads((run/'summary.json').read_text())
    build=json.loads((run/'sim/build.json').read_text());binary=run/'sim/obj/Vtb_latest_operators'
    planner=json.loads((run/'planner/build.json').read_text())
    assert summary['passed'] and summary['profile']==build['profile']==planner['profile']
    assert digest(binary)==build['binary_sha256']
    assert build['sources_unchanged_during_build'] and build['returncode']==0
    assert {'--assert','-DSYNTHESIS=1','-DXILINX_FPGA=1'}.issubset(build['command'])
    for manifest in (build,planner):
        assert manifest['sources_unchanged_during_build'] and manifest['returncode']==0
        for path,expected in manifest['source_sha256'].items():assert digest(path)==expected
    tb=(run/'sim/tb_latest_operators.sv').read_text()
    assert 'localparam int WORDS = 524288;' in tb
    assert 'u_mem.mem[i] !== golden[i]' in tb and 'assert (errors == 0)' in tb
    previous={};reference_checks={}
    for mode,directory in (('fast',args.old_fast),('registered',args.old_default)):
        if directory:
            assert args.reference
            reference=json.loads(args.reference.read_text())
            require_same_resources(summary['profile'],json.loads((directory/'summary.json').read_text())['profile'])
            reference_checks[mode]=verify_reference_sources(directory,reference,mode)
            previous[mode]={}
            for group in ('gemm','conv'):
                previous[mode].update({row['name']:row for row in json.loads((directory/group/'summary.json').read_text())['cases']})
            assert set(previous[mode])==set(public)
    rows=[]
    for group in ('gemm','conv'):
        d=json.loads((run/group/'summary.json').read_text());assert d['passed']
        assert d['source_commit']==summary['source_commit']
        assert d['build_manifest_sha256']==digest(run/'sim/build.json')
        shutil.copy2(run/group/'summary.json',out/(group+'_summary.json'))
        for row in d['cases']:
            name=row['name'];folder=run/group/'cases'/name;p=public[name]
            m=row['measurement'];t=row['timing'];ar=row['observed_ar_interval'];log=(folder/'run.log').read_text()
            assert row['passed'] and row['returncode']==0
            assert row['command'][0]==str(binary) and '+NO_RANDOM_WAIT' in row['command']
            assert [int(word,16) for word in (folder/'config.mem').read_text().split()]==row['configuration_words']
            assert ar['required']==2 and ar['minimum']>=2 and ar['accepted']==t['read_commands']
            assert m['cycles']==t['done'] and max(t['last_r'],t['last_b'])<=t['done']
            assert max(t['read_outstanding_max'],t['write_outstanding_max'])<=4
            assert t['read_latency_min']>=8 and max(t['read_burst_bytes_max'],t['write_burst_bytes_max'])<=2048
            assert records(log,'COMMON_OPERATOR_PASS')==[m] and records(log,'COMMON_TIMING')==[t]
            assert records(log,'COMMON_AR_INTERVAL')==[ar]
            for filename,expected in row['files'].items():assert digest(folder/filename)==expected
            elements=row.get('output_elements',row.get('m',0)*row.get('n',0))
            output=(folder/'canonical_output.bin').read_bytes()
            expected=memory_segment(folder/'golden.mem',row['addresses']['c'],elements)
            public_output=args.public.parent/name/'canonical_output.bin'
            assert output==expected==public_output.read_bytes() and len(output)==elements
            assert hashlib.sha256(output).hexdigest()==row['output_sha256']==row['observed_output_sha256']==p['canonical_output_sha256']
            for key,expected in p['input_tensor_sha256'].items():
                assert row['input_tensor_sha256'][key]==expected,(name,key)
            target=out/name;target.mkdir(exist_ok=True)
            (target/'canonical_output.bin').write_bytes(output)
            shutil.copy2(folder/'run.log',target/'run.log');shutil.copy2(folder/'result.json',target/'npu_result.json')
            for comparison in previous.values():
                assert row['input_tensor_sha256']==comparison[name]['input_tensor_sha256']
                assert row['output_sha256']==comparison[name]['output_sha256']
            rows.append(dict(name=name,npu_cycles=m['cycles'],
                remote_low_latency_cycles=previous['fast'][name]['measurement']['cycles'] if 'fast' in previous else None,
                remote_default_cycles=previous['registered'][name]['measurement']['cycles'] if 'registered' in previous else None,
                nvdla_engine_cycles=p['engine_cycles'],
                nvdla_configuration_cycles=p['configuration_cycles'],engine_speedup=p['engine_cycles']/m['cycles'],
                configuration_speedup=p['configuration_cycles']/m['cycles'],input_tensor_sha256=row['input_tensor_sha256'],
                output_sha256=row['output_sha256'],output_elements=elements,canonical_output_values_equal=True,
                checked_memory_words=524288,all_external_responses_completed=True,observed_ar_interval=ar,measurement=m,timing=t))
    assert len(rows)==6
    totals={key:sum(r[key] for r in rows) for key in ('npu_cycles','nvdla_engine_cycles','nvdla_configuration_cycles')}
    for mode,field in (('fast','remote_low_latency_cycles'),('registered','remote_default_cycles')):
        if mode in previous:totals[field]=sum(row[field] for row in rows)
    summary=dict(passed=True,source_commit=summary['source_commit'],profile=summary['profile'],
        binary_sha256=build['binary_sha256'],build_manifest_sha256=digest(run/'sim/build.json'),
        binary_reuse='One simulator with identical source hashes and hardware configuration for all operator collections',public_replay_source=str(args.public),public_replay_sha256=digest(args.public),
        case_count=len(rows),output_values=sum(r['output_elements'] for r in rows),
        memory_service=dict(bus_bits=64,ram_bytes=2097152,first_read_latency=8,read_beat_cycles=1,
                            read_address_interval=2,read_outstanding=4,write_outstanding=4),
        reference_source_checks=reference_checks,totals=totals,cases=rows)
    (out/'comparison.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({key:summary[key] for key in ('passed','case_count','output_values','totals')},indent=2))
    print([(r['name'],r['observed_ar_interval']) for r in rows])


if __name__=='__main__':main()
