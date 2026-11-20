#!/usr/bin/env python3
"""穷举小型原语设计输入，检查映射后寄存器输入与实际物理 LUT 真值表。"""
import argparse,hashlib,json,re,subprocess,sys
from pathlib import Path


def module(path,top=None):
    modules=json.loads(path.read_text())['modules']
    return modules[top] if top in modules else next(m for m in modules.values() if m.get('cells'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Evaluator:
    def __init__(self,m,physical_init=None):
        self.m=m;self.cells=m['cells'];self.physical_init=physical_init;self.drivers={}
        for n,c in self.cells.items():
            for port,bits in c['connections'].items():
                if c['port_directions'].get(port)=='output':
                    for i,b in enumerate(bits):
                        if isinstance(b,int):
                            assert b not in self.drivers,(b,n,self.drivers.get(b))
                            self.drivers[b]=(n,port,i)
        self.targets={}
        for n,c in self.cells.items():
            if c['type'] in ('FDRE','SLICE_FFX'):
                i=re.fullmatch(r'g_capture\[(\d+)\]\.u_register',n)
                assert i,n
                self.targets[int(i.group(1))]=c['connections']['D'][0]
        assert set(self.targets)==set(range(14))

    def run(self,value):
        self.values={'0':0,'1':1};self.busy=set();self.done=set()
        if self.m.get('ports'):
            for i,b in enumerate(self.m['ports']['i_data']['bits']):self.values[b]=(value>>i)&1
            for b in self.m['ports']['clk']['bits']:self.values[b]=0
        else:
            for i in range(8):self.values[self.cells[f'i_data[{i}]']['connections']['PAD'][0]]=(value>>i)&1
            self.values[self.cells['clk']['connections']['PAD'][0]]=0
        return sum(self.bit(bit)<<i for i,bit in self.targets.items())

    def bit(self,bit):
        if bit in self.values:return self.values[bit]
        n,port,index=self.drivers[bit]
        key=(n,port,index)
        assert key not in self.busy,('cycle',key,bit)
        self.busy.add(key)
        self.values[bit]=self.output(n,port,index)
        self.busy.remove(key)
        return self.values[bit]

    def output(self,n,port,index):
        c=self.cells[n];t=c['type'];p=c['connections']
        def read(name,position=0,default=0):
            return self.bit(p[name][position]) if len(p.get(name,[]))>position else default
        def lut_value(table,pins):
            # 只读取真值表实际依赖的输入；O5 的输入范围始终为 A1..A5。
            address=0
            for i,name in enumerate(pins):
                used=any(((table>>a)^(table>>(a|(1<<i))))&1
                         for a in range(1<<len(pins)) if not a&(1<<i))
                if used:address|=read(name)<<i
            return (table>>address)&1
        if t=='PSEUDO_GND':return 0
        if t=='PSEUDO_VCC':return 1
        if t=='IOB33_INBUF_EN':return read('PAD')
        if t=='CARRY4':
            physical='CIN' in p or any(re.fullmatch('S[0-3]',name) for name in p)
            if physical:
                ci=(int(c['parameters']['PRECYINIT_CONST'],2)
                    if 'PRECYINIT_CONST' in c.get('parameters',{}) else read('CIN')|read('CYINIT'))
                match=re.fullmatch('(CO|O)([0-3])',port);assert match,(n,port)
                output_kind=match.group(1);stage=int(match.group(2))
            else:
                ci=read('CI')|read('CYINIT');output_kind=port;stage=index
            for i in range(stage+1):
                select=read(f'S{i}') if physical else read('S',i)
                if i==stage and output_kind=='O':return select^ci
                if not select:ci=read(f'DI{i}') if physical else read('DI',i)
            return ci
        if t=='SLICE_LUTX':
            assert self.physical_init is not None
            bel=c['attributes']['NEXTPNR_BEL'];match=re.fullmatch(r'(.+/[A-D])([56])LUT',bel);assert match,bel
            site,half=match.groups();table=self.physical_init[site]
            assert port in ('O5','O6'),(n,port)
            return lut_value(table&0xffffffff if port=='O5' else table,
                             [f'A{i+1}' for i in range(5 if port=='O5' else 6)])
        if re.fullmatch(r'LUT[1-6]',t):
            return lut_value(int(c['parameters']['INIT'],2),[f'I{i}' for i in range(int(t[-1]))])
        if t=='LUT6_2':
            assert port in ('O5','O6'),(n,port)
            width=5 if port=='O5' else 6
            table=int(c['parameters']['INIT'],2)&((1<<(1<<width))-1)
            return lut_value(table,[f'I{i}' for i in range(width)])
        raise AssertionError(('unsupported data driver',n,t,port))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mapped',type=Path,required=True)
    p.add_argument('--packed',type=Path,required=True)
    p.add_argument('--physical',type=Path,required=True)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--init-checker',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    init_out=a.out/'init_check'
    subprocess.run([sys.executable,str(a.init_checker),'--packed',str(a.packed),'--physical',str(a.physical),'--source',str(a.source),'--out',str(init_out)],check=True)
    reference=module(a.mapped,'soc_top');physical=module(a.physical)
    sites=sorted({re.fullmatch(r'(.+/[A-D])([56])LUT',c['attributes']['NEXTPNR_BEL']).group(1)
        for c in physical['cells'].values() if c['type']=='SLICE_LUTX'})
    values={int(k):int(v) for k,v in (line.split() for line in subprocess.check_output([str(init_out/'physical_init')],text=True).splitlines())}
    lut_init={sites[k]:v for k,v in values.items()}
    old=Evaluator(reference);new=Evaluator(physical,lut_init)
    for value in range(256):
        expected=old.run(value);observed=new.run(value)
        assert expected==observed,(value,hex(expected),hex(observed))
    r={'passed':True,'input_vectors':256,'register_input_bits':14,'bit_comparisons':3584,
       'mapped_sha256':digest(a.mapped),'packed_sha256':digest(a.packed),'physical_sha256':digest(a.physical),
       'fasm_init_source_sha256':digest(a.source/'fasm.cc'),'physical_lut_positions':len(sites),
       'method':'Evaluate all 256 inputs at every capture FF D, using the physical INIT generated by the actual FASM function and CARRY4 Boolean equations.'}
    (a.out/'summary.json').write_text(json.dumps(r,indent=2)+'\n')
    (a.out/'physical_lut_init.json').write_text(json.dumps(lut_init,indent=2)+'\n')
    print(json.dumps(r,indent=2))


if __name__=='__main__':main()
