#!/usr/bin/env python3
"""Verify RV32 scalar numerical routines against independent Python integers and saved model tensors."""
from pathlib import Path
import argparse, ctypes as C, hashlib, json, random, subprocess
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
NN=ROOT/'drivers/tflm/NMSIS/NN'
TF=ROOT/'drivers/tflm/tflm/tflite-micro'
I=C.c_int32; L=C.c_int64; P=C.POINTER(C.c_int8)

def rne(n,d):
    q,r=divmod(n,d)
    return q+int(r>d-r or (r==d-r and q%2))
def sat(n): return max(-(1<<31),min((1<<31)-1,n))
def read_json(p): return json.loads(Path(p).read_text())
def raw(p):
    b=Path(p).read_bytes(); return (C.c_int8*len(b)).from_buffer_copy(b)
def run(cmd,log):
    result=subprocess.run([str(x) for x in cmd],cwd=ROOT,capture_output=True,text=True)
    log.write_text(result.stdout+result.stderr)
    if result.returncode: raise RuntimeError(str(log)+'\n'+(result.stdout+result.stderr)[-6000:])

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--prepared',type=Path);args=ap.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    includes=['-I'+str(p) for p in [NN/'Include',TF,TF/'tensorflow/lite/micro/tools/make/downloads/gemmlowp']]
    flags=['-O2','-g','-fPIC','-fsanitize=undefined','-fno-sanitize-recover=all','-DDSA_NN_VECTOR_ENABLE=0','-DDSA_NN_CONV_ENABLE=0','-DDSA_NN_FC_ENABLE=0','-DTF_LITE_DISABLE_X86_NEON',*includes]
    cfiles=[HERE/'native.c',NN/'Source/BasicMathFunctions/riscv_elementwise_add_s8.c']
    objects=[]
    for i,p in enumerate(cfiles):
        dest=out/f'c{i}.o';run(['gcc','-std=c11',*flags,'-include',ROOT/'test/conv_driver/host_compat.h','-c',p,'-o',dest],out/f'c{i}.log');objects.append(dest)
    cppfiles=[HERE/'native.cc',TF/'tensorflow/lite/kernels/internal/common.cc',TF/'tensorflow/lite/kernels/internal/runtime_shape.cc',TF/'tensorflow/lite/kernels/internal/quantization_util.cc']
    run(['g++','-std=c++17',*flags,'-shared','-Wl,-z,defs',*cppfiles,*objects,'-o',out/'routines.so'],out/'compile.log')
    lib=C.CDLL(str(out/'routines.so'))
    for name,types,result in [('check_nmsis_requant',[I,I,I],I),('check_tflm_requant',[I,I,I],I),('check_nmsis_s64',[L,I,I],I),('check_tflm_s64',[L,I,I],I),('check_nmsis_reduce',[I],I),('check_nmsis_divide',[L,I],I),('check_nmsis_offset',[I,I],I),('check_gemm_high',[I,I],I),('check_gemm_half',[I,I],I),('check_gemm_divide',[I,I],I),('check_gemm_divide64',[L,I],L),('check_tflm_round',[C.c_double],C.c_double),('check_tflm_add',[C.POINTER(I),P,P,P,I],None),('check_tflm_softmax',[I,I,I,P,P,I],None)]:
        f=getattr(lib,name);f.argtypes=types;f.restype=result
    add=lib.riscv_elementwise_add_s8;add.argtypes=[P,P,I,I,I,I,I,I,I,P,I,I,I,I,I,I];add.restype=I
    count=0;rng=random.Random(20261115)
    edges=[-(1<<31),-(1<<31)+1,-1073741824,-65537,-32769,-32768,-3,-2,-1,0,1,2,3,32767,32768,65535,1073741824,(1<<31)-1]
    for x in edges:
      for m in edges:
       for s in range(-31,31):
        expected=sat(rne(x*m,1<<(31-s)))
        assert lib.check_nmsis_requant(x,m,s)==expected,(x,m,s,'nmsis')
        assert lib.check_tflm_requant(x,m,s)==expected,(x,m,s,'tflm')
        count+=2
       assert lib.check_gemm_high(x,m)==sat(rne(x*m,1<<31));count+=1
       assert lib.check_gemm_half(x,m)==rne(x+m,2);count+=1
    for _ in range(50000):
      x=rng.randrange(-(1<<63),1<<63);m=rng.randrange(-(1<<31),1<<31);s=rng.randrange(-31,31)
      assert lib.check_tflm_s64(x,m,s)==sat(rne(x*m,1<<(31-s))),(x,m,s);count+=1
      x=rng.randrange(-(1<<47),1<<47);m=rng.randrange(-32768,32768);s=rng.randrange(-31,8)
      assert lib.check_nmsis_s64(x,m,s)==sat(rne(x*m,1<<(15-s)));count+=1
    for x in edges:
      for s in range(32): assert lib.check_gemm_divide(x,s)==rne(x,1<<s);count+=1
      for d in [1,2,3,4,5,7,8,49,64,125,256,32767]: assert lib.check_nmsis_divide(x,d)==sat(rne(x,d));count+=1
      assert lib.check_nmsis_reduce(x)==min(32767,rne(x,1<<16));count+=1
      for o in [-128,0,127]: assert lib.check_nmsis_offset(x,o)==sat(x+o);count+=1
    for x in [-(1<<63),-(1<<63)+1,-5,-3,-1,0,1,3,5,(1<<63)-1]:
      for s in range(64): assert lib.check_gemm_divide64(x,s)==rne(x,1<<s);count+=1
    for x in [i/2 for i in range(-1001,1002)]: assert lib.check_tflm_round(x)==round(x);count+=1
    add_elements=0
    parameters=[
        [128,-4,1623821475,-2,1073741824,0,20,1098017566,-17,-128,-128,127],
        [17,-4,1699529983,-2,1073741824,0,20,1140768826,-17,-128,-128,127],
        [-38,2,1657902019,-2,1073741824,0,20,1835721671,-18,-128,-128,127]]
    for _ in range(400):
      parameters.append([rng.randrange(-127,129),rng.randrange(-127,129),
          rng.choice([0,1,1073741824,2147483647,rng.randrange(1<<31)]),rng.randrange(-31,1),
          rng.choice([0,1,1073741824,2147483647,rng.randrange(1<<31)]),rng.randrange(-31,1),
          rng.randrange(23),rng.choice([0,1,1073741824,2147483647]),rng.randrange(-31,31),
          rng.randrange(-128,128),-128,127])
    parameters += [[0,0,1073741824,0,0,0,0,2147483647,0,0,-128,127],
                   [0,0,0,0,1073741824,0,0,2147483647,0,0,-128,127],
                   [0,0,1073741824,0,0,0,1,1073741824,0,0,-128,127],
                   [128,128,2147483647,0,2147483647,0,22,2147483647,30,127,-128,127],
                   [-127,-127,2147483647,0,2147483647,0,22,2147483647,30,-128,-128,127]]
    for index,q in enumerate(parameters):
      pairs=[(a,b) for a in range(-128,128) for b in range(-128,128)] if index<3 else [(rng.randrange(-128,128),rng.randrange(-128,128)) for _ in range(257)]
      a=(C.c_int8*len(pairs))(*(x[0] for x in pairs));b=(C.c_int8*len(pairs))(*(x[1] for x in pairs));result=(C.c_int8*len(pairs))()
      def expected_add(x,y):
        first=rne((x+q[0])*(1<<q[6])*q[2],1<<(31-q[3]))
        second=rne((y+q[1])*(1<<q[6])*q[4],1<<(31-q[5]))
        return max(q[10],min(q[11],rne((first+second)*q[7],1<<(31-q[8]))+q[9]))&255
      expected=bytes(expected_add(x,y) for x,y in pairs)
      lib.check_tflm_add((I*12)(*q),a,b,result,len(pairs));assert bytes(result)==expected,('tflm add',index,q)
      assert add(a,b,q[0],q[2],q[3],q[1],q[4],q[5],q[6],result,q[9],q[7],q[8],q[10],q[11],len(pairs))==0
      assert bytes(result)==expected,('nmsis add',index,q)
      add_elements+=len(pairs)
    nodes=[]
    if args.prepared:
      for manifest in sorted(args.prepared.glob('*/manifest.json')):
        data=read_json(manifest);base=manifest.parent;tensors={x['index']:x for x in data['graph']['tensors']}
        graph={x['index']:x for x in data['graph']['nodes']}
        for sample in data['samples']:
          outputs={x['tensor_index']:x for x in sample['nodes']};outputs[sample['input']['tensor_index']]=sample['input']
          for record in sample['nodes']:
            if record['op'] not in ('ADD','SOFTMAX'): continue
            node=graph[record['index']];params=record['integer_parameters'];a=raw(base/outputs[node['inputs'][0]]['path']);expected=(base/record['path']).read_bytes();result=(C.c_int8*len(expected))()
            if record['op']=='ADD':
              b=raw(base/outputs[node['inputs'][1]]['path']);z=[tensors[t]['zero_points'][0] for t in (*node['inputs'],node['outputs'][0])];m=params['multipliers'];s=params['shifts'];left=params['left_shift'];amin=max(-128,z[2]) if node['options']['fused_activation_function']=='RELU' else -128
              values=[-z[0],-z[1],m[0],s[0],m[1],s[1],left,m[2],s[2],z[2],amin,127];q=(I*12)(*values)
              lib.check_tflm_add(q,a,b,result,len(expected));assert bytes(result)==expected,(data['name'],sample['sample_index'],record['index'],'tflm')
              assert add(a,b,values[0],m[0],s[0],values[1],m[1],s[1],left,result,z[2],m[2],s[2],amin,127,len(expected))==0
            else:
              lib.check_tflm_softmax(params['multiplier'],params['shift'],params['diff_min'],a,result,len(expected))
            assert bytes(result)==expected,(data['name'],sample['sample_index'],record['index'],'output')
            nodes.append({'model':data['name'],'sample':sample['sample_index'],'node':record['index'],'op':record['op'],'elements':len(expected),'passed':True,'sha256':hashlib.sha256(bytes(result)).hexdigest()})
    report={'passed':True,'rounding_mode':'nearest_even','seed':20261115,'ubsan':True,'arithmetic_checks':count,'add_parameter_sets':len(parameters),'add_parameter_elements':add_elements,'add_comparisons':2*add_elements,'model_nodes':nodes,'model_elements':sum(x['elements'] for x in nodes)}
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='model_nodes'}))
if __name__=='__main__': main()
