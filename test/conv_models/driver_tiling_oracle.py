#!/usr/bin/env python3
"""Record production 0/0 auto tiling and the earlier 2/2 stress tiling."""
from pathlib import Path
import hashlib
import json
import subprocess
import tempfile
import argparse
from extract_shapes import extract_catalogue

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--models',type=Path,help='Explicit newly generated catalogue; omitted means extract TFLite now')
    ap.add_argument('--out',type=Path,default=ROOT/'build/conv_models/driver_tiling.json')
    args=ap.parse_args();args.out=args.out.resolve();args.out.parent.mkdir(parents=True,exist_ok=True)
    inventory_path=args.models.resolve() if args.models else args.out.parent/'models.json'
    if not args.models:
        inventory_path.write_text(json.dumps(extract_catalogue(),indent=2)+'\n')
    inventory_bytes=inventory_path.read_bytes()
    inventory=json.loads(inventory_bytes)
    selected=[next(layer for layer in inventory['layers'] if layer['layer_id']==layer_id)
              for layer_id in inventory['recommended_layer_ids']]
    requests=[]
    for layer in selected:
        rows=layer['output_shape'][1]*layer['output_shape'][2]
        cols=layer['output_shape'][3]//layer['groups']
        requests.extend([f'{rows} {cols} 0 0',f'{rows} {cols} 2 2'])
    with tempfile.TemporaryDirectory(prefix='conv_model_tiling_') as temp:
        binary=Path(temp)/'planner'
        command=['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror','-I',str(ROOT/'drivers'),
                 str(HERE/'driver_tiling_oracle.c'),'-o',str(binary)]
        build=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
        (args.out.parent/'driver_tiling_build.log').write_text('$ '+' '.join(command)+'\n'+build.stdout+build.stderr)
        if build.returncode:raise SystemExit(build.stderr)
        result=subprocess.run([str(binary)],input='\n'.join(requests)+'\n',capture_output=True,text=True,check=True)
    values=[list(map(int,line.split())) for line in result.stdout.splitlines()]
    assert len(values)==len(selected)*2 and all(len(v)==6 for v in values)
    names=['ia_reuse','w_reuse','row_groups','row_tail_tiles','col_groups','col_tail_tiles']
    layers=[]
    for index,layer in enumerate(selected):
        auto=dict(zip(names,values[2*index]));stress=dict(zip(names,values[2*index+1]))
        entry={'layer_id':layer['layer_id'],'model_sha256':layer['model_sha256'],
               'output_shape':layer['output_shape'],'groups':layer['groups'],
               'planner_rows':layer['output_shape'][1]*layer['output_shape'][2],
               'planner_cols':layer['output_shape'][3]//layer['groups'],
               'production_auto':auto,'requested_2_2_stress':stress,'changed':auto!=stress}
        layers.append(entry)
        print(layer['layer_id'],'auto',values[2*index],'stress',values[2*index+1],'changed',entry['changed'])
    sources=[ROOT/'drivers/gempact_tiling.h',ROOT/'drivers/dsa_conv_impl.h',
             ROOT/'drivers/tflm/NMSIS/NN/Source/ExtraAccFunctions/riscv_conv_acc.c',
             HERE/'driver_tiling_oracle.c',Path(__file__).resolve()]
    status={'verification_level':'Host C oracle calling the real production gempact_plan_capacity; no new RTL execution',
            'passed':True,
            'hardware_profile':{'size':16,'ia_cache_blocks':4,'ps_frame_count':16,
                                'is_mode':0,'per_channel':1,'pool_bytes':0},
            'production_requested':{'ia_reuse_num':0,'w_reuse_num':0},
            'stress_requested':{'ia_reuse_num':2,'w_reuse_num':2},
            'field_order':names,'models_json_sha256':hashlib.sha256(inventory_bytes).hexdigest(),
            'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
            'compiler':subprocess.check_output(['gcc','--version'],text=True).splitlines()[0],
            'layers':layers,'changed_layer_ids':[layer['layer_id'] for layer in layers if layer['changed']],
            'unchanged_layer_ids':[layer['layer_id'] for layer in layers if not layer['changed']]}
    assert inventory_path.read_bytes()==inventory_bytes, 'models.json changed during oracle'
    args.out.write_text(json.dumps(status,indent=2)+'\n')
    print(f"DRIVER_TILING_ORACLE_PASS layers={len(layers)} changed={len(status['changed_layer_ids'])} unchanged={len(status['unchanged_layer_ids'])}")

if __name__=='__main__':
    main()
