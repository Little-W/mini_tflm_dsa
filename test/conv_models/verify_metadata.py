#!/usr/bin/env python3
"""Compare extracted derived fields with actual repository C++ utility code."""
from pathlib import Path
import hashlib
import json
import subprocess
import tempfile
import argparse
from extract_shapes import extract_catalogue

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
TFLM=ROOT/'drivers/tflm/tflm/tflite-micro'

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--models',type=Path,help='Explicit newly generated catalogue; omitted means extract TFLite now')
    ap.add_argument('--out',type=Path,default=ROOT/'build/conv_models/metadata_validation.json')
    args=ap.parse_args();args.out=args.out.resolve();args.out.parent.mkdir(parents=True,exist_ok=True)
    inventory_path=args.models.resolve() if args.models else args.out.parent/'models.json'
    if not args.models:
        inventory_path.write_text(json.dumps(extract_catalogue(),indent=2)+'\n')
    data=json.loads(inventory_path.read_text())
    activation_codes={'NONE':0,'RELU':1,'RELU_N1_TO_1':2,'RELU6':3}
    lines=[]
    for layer in data['layers']:
        if not layer['regular_int8']:continue
        q=layer['quantization']
        for i,(mult,shift) in enumerate(zip(q['multipliers'],q['shifts'])):
            ws=q['filter']['scale'][i if len(q['filter']['scale'])>1 else 0]
            lines.append(f"Q {q['input']['scale'][0]:.17g} {ws:.17g} {q['output']['scale'][0]:.17g} {mult} {shift}")
        lines.append(f"A {activation_codes[layer['fused_activation']]} {q['output']['scale'][0]:.17g} "
                     f"{layer['output_offset']} {layer['activation_min']} {layer['activation_max']}")
        pad=layer['padding']
        fields=[1 if pad['mode']=='SAME' else 2,*layer['input_shape'][1:3],*layer['filter_shape'][1:3],
                *layer['stride_hw'],*layer['dilation_hw'],*layer['output_shape'][1:3],
                pad['top'],pad['left'],pad['bottom'],pad['right']]
        lines.append('P '+' '.join(map(str,fields)))
    sources=[HERE/'verify_metadata.cc',TFLM/'tensorflow/lite/kernels/internal/quantization_util.cc',
             TFLM/'tensorflow/lite/kernels/kernel_util.cc']
    with tempfile.TemporaryDirectory(prefix='conv_model_metadata_') as temp:
        binary=Path(temp)/'verify_metadata'
        command=['g++','-std=c++17','-O2','-DTF_LITE_STATIC_MEMORY','-DTFLITE_SINGLE_ROUNDING=0',
                 '-ffunction-sections','-fdata-sections','-Wl,--gc-sections','-I',str(TFLM),
                 *map(str,sources),'-o',str(binary)]
        build=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
        (args.out.parent/'metadata_validation_build.log').write_text('$ '+' '.join(command)+'\n'+build.stdout+build.stderr)
        if build.returncode:raise SystemExit(build.stderr)
        result=subprocess.run([str(binary)],input='\n'.join(lines)+'\n',capture_output=True,text=True,check=True)
        print(result.stdout,end='')
        assert 'MODEL_METADATA_ORACLE_PASS' in result.stdout
    status={'verification_level':'Derived quantization, activation range and padding against actual repository TFLite C++ utilities; no inference',
            'passed':True,'result':result.stdout.strip(),
            'models_json_sha256':hashlib.sha256(inventory_path.read_bytes()).hexdigest(),
            'compiler':subprocess.check_output(['g++','--version'],text=True).splitlines()[0],
            'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources+[Path(__file__).resolve()]}}
    args.out.write_text(json.dumps(status,indent=2)+'\n')

if __name__=='__main__':
    main()
