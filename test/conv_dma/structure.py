#!/usr/bin/env python3
"""Check real Verilator-elaborated NPU ownership of frontend and raw cache."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def child_cells(value,scope=()):
    if isinstance(value,dict):
        if value.get('type')=='CELL':
            yield scope+(value['name'],),value.get('modName', value.get('modp'))
            return
        if value.get('type') in ('GENBLOCK','BEGIN') and value.get('name'):
            scope=scope+(value['name'],)
        for child in value.values():yield from child_cells(child,scope)
    elif isinstance(value,list):
        for child in value:yield from child_cells(child,scope)


def hierarchy(tree):
    modules={node['name']:node for node in tree['modulesp'] if node.get('type')=='MODULE'}
    modules.update({node['addr']:node for node in tree['modulesp'] if node.get('type')=='MODULE'})
    result=[]
    def follow(name,path,kinds):
        module=modules[name];kind=module['origName']
        result.append({'instance':'.'.join(path),'module':kind,'module_ancestry':kinds+[kind]})
        # Children remain CELL nodes in Verilator's JSON-only elaborated AST;
        # parameter-specialized module names are resolved through modName.
        for cell_path,child_module in child_cells(module.get('stmtsp',[])):
            follow(child_module,path+list(cell_path),kinds+[kind])
    follow('tb_conv_npu',['tb_conv_npu'],[])
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-manifest',type=Path,required=True)
    parser.add_argument('--out',type=Path,default=ROOT/'build/conv_dma/structure')
    parser.add_argument('--verilator',default='verilator')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads(args.build_manifest.read_text())
    current={name:digest(ROOT/name) for name in manifest['source_sha256']}
    if current!=manifest['source_sha256']:raise RuntimeError('NPU executable does not match current source')
    tree_path=out/'hierarchy.tree.json';meta_path=out/'hierarchy.meta.json'
    cmd=[args.verilator,'--json-only','--json-only-output',tree_path,
         '--json-only-meta-output',meta_path,'--Mdir',out/'obj',
         '--timing','--assert','-sv','--top-module','tb_conv_npu','-Wno-fatal',
         '-I'+str(ROOT/'rtl/npu/ps_compact'),f'-DTB_SIZE={manifest["size"]}',
         f'-DTB_CONV_CACHE_SETS={manifest["cache_sets"]}',f'-DTB_CONV_CACHE_POLICY={manifest["cache_policy"]}',
         *[ROOT/name for name in current if Path(name).suffix in ('.sv', '.v')]]
    with (out/'elaborate.log').open('w') as stream:
        stream.write('COMMAND: '+repr([str(p) for p in cmd])+'\n');stream.flush()
        rc=subprocess.run([str(p) for p in cmd],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT).returncode
    if rc:raise RuntimeError((out/'elaborate.log').read_text()[-6000:])
    after={name:digest(ROOT/name) for name in current}
    if current!=after:raise RuntimeError('Source changed during elaboration')
    instances=hierarchy(json.loads(tree_path.read_text()))
    targets={name:[entry for entry in instances if entry['module']==name]
             for name in ['conv_im2col_frontend','conv_read_cache','conv_axi_read_guard','conv_axi_read_mux']}
    checks={}
    for name,entries in targets.items():
        checks[name+'_one_instance']=len(entries)==1
        checks[name+'_owned_by_dma']=len(entries)==1 and 'axi_dual_block_dma' in entries[0]['module_ancestry'][:-1]
        checks[name+'_outside_loaders']=all(not any(owner in e['module_ancestry'] for owner in ('ia_loader','kernel_loader')) for e in entries)
    loader_sources={}
    for name in ['ia_loader','kernel_loader']:
        path=ROOT/'rtl/npu/loaders'/f'{name}.sv'
        code=re.sub(r'/\*.*?\*/|//[^\n]*','',path.read_text(),flags=re.S)
        checks[name+'_no_raw_input_axi']=re.search(r'\b(?:[A-Za-z_]\w*_)?(?:arvalid|arready|araddr|rvalid|rready|rdata|rresp|rlast)\b',code) is None
        checks[name+'_no_conv_geometry_struct']='conv_cfg_t' not in code
        checks[name+'_matrix_descriptor_present']=all(field in code for field in ['ext_dma_im2col','ext_dma_p0','ext_dma_q0','ext_dma_group'])
        loader_sources[str(path.relative_to(ROOT))]=digest(path)
    legacy=ROOT/'rtl/npu/conv/conv_ia_tile_path.sv'
    report={'passed':all(checks.values()),'checks':checks,'elaborated_instances':targets,
            'checker_sha256':digest(Path(__file__)),
            'loader_sources':loader_sources,'compiled_source_sha256':current,
            'source_sha256_after':after,'source_unchanged':current==after,
            'executable_build_manifest':str(args.build_manifest.resolve()),
            'executable_build_manifest_sha256':digest(args.build_manifest),
            'verilator':subprocess.check_output([args.verilator,'--version'],text=True).strip(),
            'command':[str(p) for p in cmd],
            'tree_raw_sha256':digest(tree_path),'metadata_sha256':digest(meta_path),
            'inactive_compatibility_adapter':{
                'source':str(legacy.relative_to(ROOT)),'sha256':digest(legacy),
                'elaborated_in_npu':any(e['module']=='conv_ia_tile_path' for e in instances),
                'note':'This retained standalone helper contains a frontend instance in its source, but is not instantiated by the active NPU hierarchy. The ownership assertion concerns elaborated hardware, not an uninstantiated module definition.'}}
    with (out/'hierarchy.tree.json.gz').open('wb') as f:
        f.write(gzip.compress(tree_path.read_bytes(),mtime=0))
    tree_path.unlink()
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print('DMA_STRUCTURE_PASS' if report['passed'] else 'DMA_STRUCTURE_FAIL',len(checks),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':sys.exit(main())
