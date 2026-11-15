#!/usr/bin/env python3
"""Check convolution, Add, pooling and dense references using NumPy integer math.

Weights are decoded from the TFLite file. Input tensors and Q31 coefficients
come from the prepared manifest. This checker has no production C or RTL
arithmetic dependency. Softmax is verified separately by test/software_rne.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import numpy as np

from model_data import MODELS, validate_model

ROOT=Path(__file__).resolve().parents[2]

def rne(value,denominator):
    q=np.floor_divide(value,denominator)
    r=value-q*denominator
    return q+((r>denominator-r)|((r==denominator-r)&((q&1)!=0)))

def requant(value,parameters):
    mult=np.array(parameters['multipliers'],dtype=np.int64)
    shift=np.array(parameters['shifts'],dtype=np.int64)
    return rne(value*mult,np.left_shift(np.int64(1),31-shift))

def limits(tensor,activation):
    q=tensor['quantization'];zp=q['zero_points'][0];scale=q['scales'][0]
    if activation=='NONE':return -128,127
    if activation=='RELU':return max(-128,zp),127
    if activation=='RELU6':return max(-128,zp),min(127,round(6/scale)+zp)
    if activation=='RELU_N1_TO_1':return max(-128,round(-1/scale)+zp),min(127,round(1/scale)+zp)
    raise ValueError('Unsupported activation '+activation)

def load_schema():
    path=ROOT/'drivers/tflm/tflm/tflite-micro/tensorflow/lite/python/schema_py_generated.py'
    spec=importlib.util.spec_from_file_location('benchmark_schema',path)
    schema=importlib.util.module_from_spec(spec);spec.loader.exec_module(schema)
    return schema

def verify(directory,schema):
    validate_model(directory)
    manifest=json.loads((directory/'manifest.json').read_text())
    model=schema.Model.GetRootAsModel((directory/'model.tflite').read_bytes(),0)
    graph=model.Subgraphs(0)
    metadata={t['index']:t for t in manifest['graph']['tensors']}
    constants={}
    for i,t in metadata.items():
        buffer=model.Buffers(graph.Tensors(i).Buffer())
        if buffer.DataLength():
            constants[i]=np.frombuffer(buffer.DataAsNumpy().tobytes(),dtype=t['dtype']).reshape(t['shape'])
    reports=[]
    for sample in manifest['samples']:
        tensors=dict(constants)
        tensor=sample['input']
        tensors[tensor['tensor_index']]=np.frombuffer((directory/tensor['path']).read_bytes(),dtype=np.int8).reshape(tensor['shape'])
        checked=0;outputs=0
        for node,expected in zip(manifest['graph']['nodes'],sample['nodes']):
            op=node['op'];options=node['options'];indices=node['inputs'];out=node['outputs'][0]
            out_meta=metadata[out];out_shape=out_meta['shape'];out_zp=out_meta['zero_points'][0]
            source=tensors[indices[0]].astype(np.int64)
            zp=metadata[indices[0]]['zero_points'][0]
            parameters=expected['integer_parameters']
            golden=np.frombuffer((directory/expected['path']).read_bytes(),dtype=expected['dtype']).reshape(expected['shape'])
            if op=='SOFTMAX':
                tensors[out]=golden
                continue
            if op in ('CONV_2D','DEPTHWISE_CONV_2D','AVERAGE_POOL_2D','MAX_POOL_2D'):
                kh,kw=options['kernel_h'],options['kernel_w'];sh,sw=options['stride_h'],options['stride_w']
                dh,dw=options.get('dilation_h_factor',1),options.get('dilation_w_factor',1)
                _,ih,iw,ic=source.shape;_,oh,ow,oc=out_shape
                ph=max(0,(oh-1)*sh+(kh-1)*dh+1-ih)//2 if options['padding']=='SAME' else 0
                pw=max(0,(ow-1)*sw+(kw-1)*dw+1-iw)//2 if options['padding']=='SAME' else 0
                accum=np.zeros(out_shape,dtype=np.int64)
                count=np.zeros((1,oh,ow,1),dtype=np.int64)
                if op=='MAX_POOL_2D':accum.fill(-128)
                if op in ('CONV_2D','DEPTHWISE_CONV_2D'):
                    weight=tensors[indices[1]].astype(np.int64)
                    accum+=tensors[indices[2]].astype(np.int64) if len(indices)>2 and indices[2]>=0 else 0
                for ky in range(kh):
                    iy=np.arange(oh)*sh+ky*dh-ph;valid_y=(iy>=0)&(iy<ih)
                    for kx in range(kw):
                        ix=np.arange(ow)*sw+kx*dw-pw;valid_x=(ix>=0)&(ix<iw)
                        valid=(valid_y[:,None]&valid_x[None,:])[None,:,:,None]
                        pixels=source[:,np.clip(iy,0,ih-1)[:,None],np.clip(ix,0,iw-1)[None,:],:]
                        if op=='CONV_2D':
                            accum+=np.tensordot(np.where(valid,pixels-zp,0),weight[:,ky,kx,:],axes=([-1],[-1]))
                        elif op=='DEPTHWISE_CONV_2D':
                            if options['depth_multiplier']!=1:raise ValueError('Depth multiplier must be one')
                            accum+=np.where(valid,pixels-zp,0)*weight[0,ky,kx,:]
                        elif op=='AVERAGE_POOL_2D':
                            accum+=np.where(valid,pixels,0);count+=valid
                        else:accum=np.maximum(accum,np.where(valid,pixels,-128))
                if op in ('CONV_2D','DEPTHWISE_CONV_2D'):result=requant(accum,parameters)+out_zp
                elif op=='AVERAGE_POOL_2D':result=rne(accum,count)
                else:result=accum
            elif op=='FULLY_CONNECTED':
                weight=tensors[indices[1]].astype(np.int64)
                result=(source.reshape(-1,weight.shape[-1])-zp)@weight.T
                if len(indices)>2 and indices[2]>=0:result+=tensors[indices[2]].astype(np.int64)
                result=requant(result,parameters)+out_zp
            elif op=='ADD':
                other=tensors[indices[1]].astype(np.int64);other_zp=metadata[indices[1]]['zero_points'][0]
                mult=parameters['multipliers'];shift=parameters['shifts'];left=parameters['left_shift']
                a=rne((source-zp)*(1<<left)*mult[0],1<<(31-shift[0]))
                b=rne((other-other_zp)*(1<<left)*mult[1],1<<(31-shift[1]))
                result=rne((a+b)*mult[2],1<<(31-shift[2]))+out_zp
            elif op=='RESHAPE':result=source.reshape(out_shape)
            else:raise ValueError('Unsupported operator '+op)
            lo,hi=limits(out_meta,options.get('fused_activation_function','NONE'))
            actual=np.clip(result,lo,hi).astype(np.int8).reshape(out_shape)
            if not np.array_equal(actual,golden):
                location=tuple(np.argwhere(actual!=golden)[0])
                raise ValueError(f'{manifest["name"]} sample {sample["sample_index"]} node {node["index"]} at {location}: {actual[location]} != {golden[location]}')
            tensors[out]=actual;checked+=1;outputs+=actual.size
        reports.append({'sample':sample['sample_index'],'nodes':checked,'outputs':outputs,'passed':True})
    return {'model':manifest['name'],'samples':reports,'passed':True}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prepared',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();schema=load_schema()
    reports=[verify(args.prepared/name,schema) for name in MODELS]
    value={'passed':True,'reference':'Independent integer graph evaluation with quotient and remainder RNE',
           'softmax_validation':'test/software_rne','models':reports}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(value,indent=2)+'\n')
    print(json.dumps(value,indent=2))

if __name__=='__main__':main()
