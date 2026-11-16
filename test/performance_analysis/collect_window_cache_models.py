#!/usr/bin/env python3
"""Validate complete-model depthwise cache counters and write their summary."""
from pathlib import Path
import argparse
import collections
import datetime
import hashlib
import json
import math
import os
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
parser.add_argument("--measurements", type=Path, required=True)
parser.add_argument("--expected-commit")
parser.add_argument("--native-conv", type=Path)
args = parser.parse_args()
repo = args.repo.resolve()
base = args.measurements.resolve()
commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
if args.expected_commit and commit != args.expected_commit:
    raise ValueError("Repository commit differs from the requested measurement release")
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def obj(p):return json.loads(Path(p).read_text())
def ref(p):return {'path':os.path.relpath(p,base),'sha256':sha(p)}
build_path=base/'sim/build.json';build=obj(build_path)
assert build['returncode']==0 and build['sources_unchanged_during_build']
source_checks=[]
for name,h in build['source_sha256'].items():
 if name.startswith(('rtl/','drivers/')):
  current=sha(repo/name);source_checks.append({'path':name,'recorded_sha256':h,'current_sha256':current,'matches':h==current})
assert all(c['matches'] for c in source_checks)
records=[];sources=[];manifests={};network_checks=[];seen=set();all_model_samples=[]
expected_counts={'ds_cnn_kws':4,'mobilenet_v1_vww':13,'mnist_cnn':0,'resnet8_cifar10':0}
raw_fields=['window_cache_hits','window_cache_misses','window_cache_read_bytes','npu_read_bytes','npu_write_bytes','npu_read_bursts','npu_write_bursts','cycles','npu_busy_cycles','dw_jobs','dw_done','dw_windows','npu_errors','axi_errors','vector_compute_cycles','vector_dma_wait_cycles']
trace_results=sorted(base.glob('results/cases/*/*/trace_63/result.json'))
assert len(trace_results)==8
for p in trace_results:
 result=obj(p);case_path=p.with_name('case.json');case=obj(case_path);model=result['model_id'];sample=result['sample_index']
 assert result['passed'] and result['mode']==63 and result['kind']=='trace' and all(result['checks'].values())
 assert result['simulator']['simulator_sha256']==build['binary_sha256']
 manifest_path=Path(case['prepared_dir'])/'manifest.json';manifest=obj(manifest_path)
 assert sha(manifest_path)==case['prepared_sha256']
 assert result['model']['sha256']==manifest['model']['sha256']==case['model']['sha256']
 assert result['input_sha256']==case['sample']['input']['sha256']
 manifests[model]={'model_sha256':manifest['model']['sha256'],'prepared_manifest':ref(manifest_path)}
 nodes={n['index']:n for n in manifest['graph']['nodes']};layers={r['index']:r for r in result['layers']}
 assert len(layers)==len(result['layers']) and set(layers)==set(nodes)
 perf_path=p.parent.parent/'perf_63/result.json';perf=obj(perf_path)
 assert perf['passed'] and perf['model_id']==model and perf['sample_index']==sample and perf['kind']=='perf' and perf['mode']==63
 assert perf['simulator']['simulator_sha256']==build['binary_sha256']
 source={'model':model,'sample_index':sample,'trace_result':ref(p),'case':ref(case_path),'perf_result':ref(perf_path),
         'input_sha256':result['input_sha256'],'model_sha256':result['model']['sha256'],'firmware_elf_sha256':result['firmware_elf_sha256'],
         'trace_checks_all_passed':True,'perf_passed':True,'simulator_sha256':result['simulator']['simulator_sha256']}
 sources.append(source)
 for field in ['window_cache_hits','window_cache_misses','window_cache_read_bytes']:
  total=sum(r[field] for r in layers.values());assert total==result['network'][field]
  network_checks.append({'model':model,'sample_index':sample,'field':field,'sum_of_all_layers':total,'network_counter':result['network'][field],'passed':True})
 selected=[n for n in manifest['graph']['nodes'] if n['op']=='DEPTHWISE_CONV_2D'];assert len(selected)==expected_counts[model]
 all_model_samples.append({'model':model,'sample_index':sample,'expected_dw_layers':len(selected),'observed_dw_layers':len(selected)})
 for node in selected:
  index=node['index'];r=layers[index];key=(model,sample,index);assert key not in seen;seen.add(key)
  assert r['dw_jobs']==r['dw_done']==1 and r['npu_errors']==r['axi_errors']==0
  assert all(r[k]>=0 for k in raw_fields)
  h,m=r['window_cache_hits'],r['window_cache_misses'];d=h+m;assert d>0
  traces=[t for t in result['trace'] if t['descriptor']['operator_index']==index]
  assert traces and all(t['passed'] and t['comparison']['passed'] for t in traces)
  input_bytes=math.prod(node['input_shapes'][0]);weight_bytes=math.prod(node['input_shapes'][1]);channels=node['input_shapes'][0][-1]
  bias_bytes=math.prod(node['input_shapes'][2])*4 if len(node['input_shapes'])>2 else 0
  output_bytes=math.prod(node['output_shapes'][0]);parameter_bytes=weight_bytes+bias_bytes+8*channels
  assert r['window_cache_read_bytes']==input_bytes
  assert r['npu_read_bytes']==input_bytes+parameter_bytes and r['npu_write_bytes']==output_bytes
  records.append({'model':model,'sample_index':sample,'layer_index':index,'operator':'DEPTHWISE_CONV_2D',
   'input_shape':node['input_shapes'][0],'output_shape':node['output_shapes'][0],'weight_shape':node['input_shapes'][1],'options':node['options'],
   'input_tensor_bytes':input_bytes,'output_tensor_bytes':output_bytes,'parameter_bytes':parameter_bytes,
   **{k:r[k] for k in raw_fields},'demand_requests':d,'demand_hit_rate_percent':100*h/d,'meets_99_percent':100*h>=99*d,
   'input_read_amplification':r['window_cache_read_bytes']/input_bytes,'one_input_tensor_read':r['window_cache_read_bytes']==input_bytes,
   'total_read_equals_input_and_parameters':r['npu_read_bytes']==input_bytes+parameter_bytes,'output_exact':True,
   'output_sha256':[t['comparison']['actual_sha256'] for t in traces],
   'source_result':ref(p),'source_case':ref(case_path)})
assert len(records)==34 and len({(r['model'],r['layer_index']) for r in records})==17
assert sorted({r['sample_index'] for r in records})==[0,1]
def aggregate(rows):
 h=sum(r['window_cache_hits'] for r in rows);m=sum(r['window_cache_misses'] for r in rows)
 return {'records':len(rows),'hits':h,'misses':m,'demand_requests':h+m,'weighted_hit_rate_percent':100*h/(h+m) if h+m else None,
  'window_cache_read_bytes':sum(r['window_cache_read_bytes'] for r in rows),'input_tensor_bytes':sum(r['input_tensor_bytes'] for r in rows),
  'npu_read_bytes':sum(r['npu_read_bytes'] for r in rows),'npu_write_bytes':sum(r['npu_write_bytes'] for r in rows),
  'minimum_layer_sample_hit_rate_percent':min((r['demand_hit_rate_percent'] for r in rows),default=None),
  'records_meeting_99_percent':sum(r['meets_99_percent'] for r in rows),'all_input_read_amplification_one':all(r['one_input_tensor_read'] for r in rows)}
layer_summaries=[]
for model,index in sorted({(r['model'],r['layer_index']) for r in records}):
 rows=[r for r in records if r['model']==model and r['layer_index']==index];assert len(rows)==2
 summary=aggregate(rows);minimum=summary['minimum_layer_sample_hit_rate_percent']
 layer_summaries.append({'model':model,'layer_index':index,'samples':[r['sample_index'] for r in rows],'input_shape':rows[0]['input_shape'],'output_shape':rows[0]['output_shape'],'options':rows[0]['options'],
  **summary,'minimum_sample_indices':[r['sample_index'] for r in rows if r['demand_hit_rate_percent']==minimum],
  'per_sample':[{'sample_index':r['sample_index'],'hits':r['window_cache_hits'],'misses':r['window_cache_misses'],'hit_rate_percent':r['demand_hit_rate_percent'],
    'window_cache_read_bytes':r['window_cache_read_bytes'],'npu_read_bytes':r['npu_read_bytes']} for r in rows]})
model_summaries=[]
for model,count in sorted(expected_counts.items()):
 rows=[r for r in records if r['model']==model];summary=aggregate(rows)
 model_summaries.append({'model':model,'dw_layer_count':count,'samples':[0,1],**summary,
  'mean_window_cache_read_bytes_per_inference':summary['window_cache_read_bytes']/2,
  'per_sample':[{'sample_index':sample,**aggregate([r for r in rows if r['sample_index']==sample])} for sample in [0,1]]})
overall=aggregate(records);minimum=overall['minimum_layer_sample_hit_rate_percent']
report={'schema_version':1,'release_commit':commit,'generated_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'path_base':'directory containing this report',
 'passed':True,'measurement':'Actual complete-model hardware trace counters, mode 63, two inputs per model',
 'target_demand_hit_rate_percent':99,'target_passed':all(r['meets_99_percent'] for r in records),
 'source_build':ref(build_path),'source_build_production_files':source_checks,'all_recorded_build_production_files_match_release':True,
 'simulator_sha256':build['binary_sha256'],'source_results':sources,'model_manifests':manifests,
 'definitions':{'demand_hit_rate_percent':'100 * hits / (hits + misses); cold demands are included',
   'weighted_hit_rate_percent':'100 * sum(hits) / (sum(hits) + sum(misses))',
   'window_cache_read_bytes':'All input-window bytes fetched from external memory, including prefetch fills',
   'input_read_amplification':'window_cache_read_bytes / allocated input tensor bytes',
   'minimum_layer_hit_rate':'Minimum of the two independently observed input-specific rates',
   'record_selection':'Join hardware trace layers[index] to the prepared model graph; select DEPTHWISE_CONV_2D',
   'parameter_bytes':'S8 weights + S32 bias + S32 per-channel multiplier + S32 per-channel shift',
   'prefetch_statistics':'SoC result records do not expose prefetch used/wasted/unused/late counts. Explicit prefetch statistics remain in component validation records.'},
 'coverage':{'expected_unique_layers':17,'observed_unique_layers':17,'expected_layer_sample_records':34,'observed_layer_sample_records':34,'complete':True,
   'model_sample_coverage':all_model_samples,'all_layer_outputs_exact':True,'all_layer_samples_meet_99_percent':all(r['meets_99_percent'] for r in records),
   'all_input_read_amplification_one':all(r['one_input_tensor_read'] for r in records),'all_npu_read_bytes_equal_input_and_parameters':all(r['total_read_equals_input_and_parameters'] for r in records)},
 'network_counter_consistency':network_checks,'overall':overall,
 'minimum_records':[{'model':r['model'],'sample_index':r['sample_index'],'layer_index':r['layer_index'],'hits':r['window_cache_hits'],'misses':r['window_cache_misses'],'hit_rate_percent':r['demand_hit_rate_percent']} for r in records if r['demand_hit_rate_percent']==minimum],
 'models':model_summaries,'layers':layer_summaries,'records':records}
out=base/'window_cache_models.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
# Validate serialization, every source checksum, and aggregate arithmetic.
check=obj(out);assert check['coverage']['complete']
for s in check['source_results']:
 for key in ['trace_result','case','perf_result']:assert sha(base/s[key]['path'])==s[key]['sha256']
assert sum(r['window_cache_hits'] for r in check['records'])==check['overall']['hits']
assert sum(r['window_cache_misses'] for r in check['records'])==check['overall']['misses']
if args.native_conv:
    native_path = args.native_conv.resolve()
    native = obj(native_path)
    assert native['passed']
    native_build = obj(native_path.parent/'sim/build.json')
    assert native_build['returncode']==0 and native_build['sources_unchanged_during_build']
    for name,digest in native_build['source_sha256'].items():
        if name.startswith(('rtl/','drivers/')):
            assert sha(repo/name)==digest,name
    assert len(native['cases']) == 3 and all(c['passed'] for c in native['cases'])
    native_rows = []
    for case in native['cases']:
        measured = case['measurement']
        requests = measured['hits'] + measured['misses']
        assert requests > 0
        shape = case['conv']
        input_bytes = shape['batch'] * shape['input_h'] * shape['input_w'] * shape['input_channels']
        native_rows.append({
            'name': case['name'], 'operator': case['operator'], **measured,
            'allocated_input_tensor_bytes': input_bytes,
            'demand_hit_rate_percent': 100 * measured['hits'] / requests,
            'input_read_amplification': measured['input_bytes'] / input_bytes,
            'workload_manifest_sha256': case['workload_manifest_sha256'],
            'output_sha256': case['output_sha256'], 'passed': True,
        })
    model_names = {'ds_cnn_kws': 'DS-CNN KWS', 'mobilenet_v1_vww': 'MobileNetV1 VWW'}
    lines = [
        '实际完整模型的 DW 统计如下，计数为两个输入的合计：', '',
        '| 模型 | DW 层数 | Hits | Misses | 加权需求命中率 | 窗口读取字节 |',
        '| --- | ---: | ---: | ---: | ---: | ---: |',
    ]
    for model in model_summaries:
        if not model['dw_layer_count']:
            continue
        lines.append(f"| {model_names[model['model']]} | {model['dw_layer_count']} | "
                     f"{model['hits']:,} | {model['misses']:,} | "
                     f"{model['weighted_hit_rate_percent']:.6f}% | {model['window_cache_read_bytes']:,} |")
    lines.extend([
        '',
        f"17 个 DW 层、两个输入共 34 项中，{overall['records_meeting_99_percent']} 项的需求命中率达到 99%，最低为 {minimum:.8f}%。"
        '每项 DW 窗口读取字节均等于输入张量大小，输入读取放大率为 1.0。', '',
        '| 共同算子 | 周期 | Hits | Misses | 需求命中率 | 窗口读取字节 | 输入读取放大率 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: |',
    ])
    for row in native_rows:
        lines.append(f"| {row['name']} | {row['cycles']:,} | {row['hits']:,} | {row['misses']:,} | "
                     f"{row['demand_hit_rate_percent']:.6f}% | {row['input_bytes']:,} | "
                     f"{row['input_read_amplification']:.6f} |")
    lines.extend([
        '',
        '需求命中率采用 Hits / (Hits + Misses)，包含冷启动需求；窗口读取字节包含预取填充。'
        '完整模型的需求命中率与读取放大率统计范围是上述 17 个 DW 层。'
    ])
    for row in native_rows:
        if row['operator'] == 'conv2d':
            lines.append(f"共同普通 Conv 的输入张量为 {row['allocated_input_tensor_bytes']:,} B，"
                         f"窗口读取为 {row['input_bytes']:,} B，其读取放大率单独列出。")
    combined = {
        'passed': True, 'models': check, 'native_convolution_source': ref(native_path),
        'native_convolution': native_rows,
        'native_dw': [row for row in native_rows if row['operator'] == 'depthwise'],
        'report_markdown': '\n'.join(lines) + '\n',
    }
    combined_path = base / 'window_cache.json'
    combined_path.write_text(json.dumps(combined, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({"passed": True, "report": str(out), "sha256": sha(out),
                  "target_passed": check['target_passed'],
                  "depthwise_layers": check["coverage"]["observed_unique_layers"],
                  "layer_input_executions": len(check["records"]),
                  "minimum_demand_hit_rate_percent": minimum,
                  "weighted_demand_hit_rate_percent": overall["weighted_hit_rate_percent"]}, indent=2))
