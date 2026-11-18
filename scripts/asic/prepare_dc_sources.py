#!/usr/bin/env python3
"""Prepare explicit optional-port connections for Design Compiler analysis."""
import argparse
import json
import re
from pathlib import Path


def closing(text, start):
    depth=0
    for index in range(start,len(text)):
        if text[index]=='(': depth+=1
        elif text[index]==')':
            depth-=1
            if not depth:return index
    raise ValueError('Unbalanced module or instance declaration')


def pieces(text):
    depth=0;start=0
    for i,ch in enumerate(text):
        if ch in '({[':depth+=1
        elif ch in ')}]':depth-=1
        elif ch==',' and depth==0:
            yield start,i,text[start:i];start=i+1
    yield start,len(text),text[start:]


def prepare(root,filelist,destination):
    destination.mkdir(parents=True,exist_ok=True)
    files=[];includes=[]
    for line in filelist.read_text().splitlines():
        line=line.strip()
        if not line or line.startswith('#'):continue
        if line.startswith('+incdir+'):
            includes.append((filelist.parent.parent/line[8:]).resolve())
        else:files.append((filelist.parent.parent/line).resolve())
    source={p:p.read_text() for p in files}
    modules={};removals={p:[] for p in files}
    for path,text in source.items():
        clean=re.sub(r'//[^\n]*|/\*.*?\*/',lambda m:' '*len(m[0]),text,flags=re.S)
        for match in re.finditer(r'\bmodule\s+(\w+)\s*',clean):
            pos=match.end();params={}
            if clean[pos:pos+1]=='#':
                opening=clean.index('(',pos);end=closing(clean,opening)
                for _,_,piece in pieces(clean[opening+1:end]):
                    declaration=re.search(r'(\w+)\s*=\s*(.*)',piece,re.S)
                    if declaration:params[declaration[1]]=declaration[2].strip()
                pos=end+1
            opening=clean.index('(',pos);end=closing(clean,opening);defaults={}
            direction=''
            for a,b,piece in pieces(clean[opening+1:end]):
                d=re.search(r'\b(input|output|inout)\b',piece)
                if d:direction=d[1]
                default=re.search(r'\b(\w+)\s*(?:\[[^]]*\]\s*)*=\s*(.*)',piece,re.S)
                if direction=='input' and default:
                    defaults[default[1]]=default[2].strip()
                    eq=piece.index('=',default.start())
                    removals[path].append((opening+1+a+eq,opening+1+b,''))
            modules[match[1]]=(params,defaults)
    for path,text in source.items():
        clean=re.sub(r'//[^\n]*|/\*.*?\*/',lambda m:' '*len(m[0]),text,flags=re.S)
        for name,(params,defaults) in modules.items():
            if not defaults:continue
            pattern=re.compile(r'\b'+re.escape(name)+r'\s*(?=#|[A-Za-z_])')
            for match in pattern.finditer(clean):
                if re.search(r'\bmodule\s*$',clean[max(0,match.start()-12):match.start()]):continue
                pos=match.end();overrides={}
                if clean[pos:pos+1]=='#':
                    opening=clean.index('(',pos);end=closing(clean,opening)
                    for _,_,piece in pieces(text[opening+1:end]):
                        arg=re.search(r'\.\s*(\w+)\s*\(',piece)
                        if arg:
                            l=piece.index('(',arg.start());r=closing(piece,l)
                            overrides[arg[1]]=piece[l+1:r].strip()
                    pos=end+1
                instance=re.match(r'\s*\w+\s*\(',clean[pos:])
                if not instance:continue
                opening=pos+instance.end()-1;end=closing(clean,opening)
                connections=clean[opening+1:end]
                if re.search(r'\.\s*\*',connections):continue
                connected=set(re.findall(r'\.\s*(\w+)',connections))
                additions=[]
                for port,value in defaults.items():
                    if port in connected:continue
                    def expand(token,seen=frozenset()):
                        if token in overrides:return '('+overrides[token]+')'
                        if token not in params or token in seen:return token
                        return '('+re.sub(r'\b[A-Za-z_]\w*\b',lambda m:expand(m[0],seen|{token}),params[token])+')'
                    value=re.sub(r'\b[A-Za-z_]\w*\b',lambda m:expand(m[0]),value)
                    additions.append('.'+port+'('+value+')')
                if additions:removals[path].append((end,end,(',' if connections.strip() else '')+','.join(additions)))
        updated=text
        for a,b,value in sorted(removals[path],reverse=True):updated=updated[:a]+value+updated[b:]
        target=destination/path.relative_to(root);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(updated)
    output=destination/'sources.f'
    output.write_text('\n'.join(['+incdir+'+str(p) for p in includes]+[str(destination/p.relative_to(root)) for p in files])+'\n')
    (destination/'transformations.json').write_text(json.dumps({str(p.relative_to(root)):len(v) for p,v in removals.items()},indent=2)+'\n')
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2])
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--filelist',type=Path)
    args=parser.parse_args()
    filelist=args.filelist.resolve() if args.filelist else args.root.resolve()/'asic/synthesis/filelists/npu_top.f'
    print(prepare(args.root.resolve(),filelist,args.out.resolve()))
