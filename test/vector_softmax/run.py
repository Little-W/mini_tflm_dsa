#!/usr/bin/env python3
"""Compare VCE Softmax RTL with TFLM RNE arithmetic and saved model outputs."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
TF=ROOT/'drivers/tflm/tflm/tflite-micro'

def command(argv,log):
    result=subprocess.run([str(x) for x in argv],cwd=ROOT,capture_output=True,text=True)
    log.write_text(result.stdout+result.stderr)
    if result.returncode:
        raise RuntimeError(str(log)+'\n'+(result.stdout+result.stderr)[-8000:])
    return result.stdout

def signed_values(base,record):
    data=(base/record['path']).read_bytes()
    if len(data)!=record['bytes'] or hashlib.sha256(data).hexdigest()!=record['sha256']:
        raise ValueError('Saved tensor identity differs: '+record['path'])
    return [x if x<128 else x-256 for x in data]

def prepare_replay(prepared,destination):
    records=[]
    if prepared:
        for manifest in sorted(prepared.glob('*/manifest.json')):
            data=json.loads(manifest.read_text());base=manifest.parent
            if data['rounding_mode']!='nearest_even':raise ValueError('Replay requires nearest-even references')
            graph={x['index']:x for x in data['graph']['nodes']}
            for sample in data['samples']:
                tensors={x['tensor_index']:x for x in sample['nodes']}
                tensors[sample['input']['tensor_index']]=sample['input']
                for record in sample['nodes']:
                    if record['op']!='SOFTMAX': continue
                    node=graph[record['index']];params=record['integer_parameters']
                    a=signed_values(base,tensors[node['inputs'][0]])
                    b=signed_values(base,record)
                    label=f"{data['name']}_{sample['sample_index']}_{record['index']}"
                    records.append([label,params['multiplier'],params['shift'],params['diff_min'],len(a),*a,*b])
    destination.write_text(''.join(' '.join(map(str,r))+'\n' for r in records))
    return len(records)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--prepared',type=Path)
    parser.add_argument('--depths',type=int,nargs='+',default=[16,32])
    parser.add_argument('--verilator',default='verilator')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    replay=out/'model_cases.txt';models=prepare_replay(args.prepared,replay);records=[]
    includes=[TF,TF/'tensorflow/lite/micro/tools/make/downloads/gemmlowp']
    for depth in args.depths:
        folder=out/f'depth_{depth}';folder.mkdir(exist_ok=True)
        flags=['-std=c++17','-O2','-fsanitize=undefined','-fno-sanitize-recover=all',
               '-DTF_LITE_DISABLE_X86_NEON',f'-DTEST_MAX_DEPTH={depth}',*['-I'+str(p) for p in includes]]
        cmd=[args.verilator,'--cc','--exe','--build','-j','2','-Wno-fatal',
             '--top-module','vector_softmax_test','--Mdir',folder/'obj',f'-GMAX_DEPTH={depth}',
             '-CFLAGS',' '.join(flags),'-LDFLAGS','-fsanitize=undefined',
             ROOT/'rtl/npu/conv/vector_softmax.sv',HERE/'vector_softmax_test.sv',HERE/'main.cpp',
             TF/'tensorflow/lite/kernels/internal/common.cc',
             TF/'tensorflow/lite/kernels/internal/runtime_shape.cc',
             TF/'tensorflow/lite/kernels/internal/quantization_util.cc']
        command(cmd,folder/'build.log')
        stdout=command([folder/'obj/Vvector_softmax_test',replay,folder/'model_replay.bin'],folder/'run.log')
        record=json.loads(stdout.strip().splitlines()[-1]);records.append(record)
        assert record['model_cases']==models
        print(stdout,end='',flush=True)
    result={'passed':True,'rounding_mode':'nearest_even','ubsan':True,'seed':20261115,
            'model_cases_per_configuration':models,'configurations':records}
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')

if __name__=='__main__':main()
