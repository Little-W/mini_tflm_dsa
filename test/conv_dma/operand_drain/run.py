#!/usr/bin/env python3
"""Verify retirement after a held prefetch suffix on current production RTL."""
from pathlib import Path
import argparse,hashlib,json,re,shutil,subprocess,sys
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def command(args,log,timeout=1200):
    with log.open('w') as f:
        f.write('COMMAND: '+repr([str(a) for a in args])+'\n');f.flush()
        return subprocess.run(list(map(str,args)),cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,timeout=timeout).returncode
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,default=ROOT/'build/conv_dma/operand_drain')
    p.add_argument('--verilator',default='verilator');p.add_argument('--jobs',type=int,default=2)
    p.add_argument('--skip-build',action='store_true')
    p.add_argument('--reuse-build-root',type=Path,help='Optional compiled profile; every source/include hash must match')
    a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    source_root=ROOT
    npu=source_root/'rtl/npu';packages=[npu/'conv/conv_im2col_pkg.sv',npu/'conv/vector_engine_pkg.sv']
    sources=packages+[s for s in sorted(npu.rglob('*.sv')) if s not in packages]+sorted(npu.rglob('*.v'))
    sources+=[source_root/'rtl/common/pseudo_dual_port_ram.v',source_root/'rtl/axi_top/npu_axil_top.sv',source_root/'rtl/axi_top/npu_axil_reg_if.sv',source_root/'test/conv_npu/axi_memory.sv',source_root/'test/conv_dma/operand_drain/tb_operand_drain.sv']
    config=source_root/'test/conv_npu/simulator.vlt'
    dependencies=sources+sorted(npu.rglob('*.svh'))+[config]
    hashes={str(s.relative_to(source_root)):sha(s) for s in dependencies}
    manifest=out/'build.json';binary=out/'obj/Vtb_operand_drain'
    if not a.skip_build:
        args=[a.verilator,'--binary','--timing','--assert','-sv','--top-module','tb_operand_drain','-Wno-fatal','--output-groups','0','--output-split','10000','--output-split-cfuncs','1000',f'-I{npu/"ps_compact"}','--Mdir',out/'obj','-j',a.jobs,'-CFLAGS','-std=c++20 -O1','-MAKEFLAGS','OPT_FAST=-O1 OPT_SLOW=-O0',config,*sources]
        rc=command(args,out/'build.log');txt=(out/'build.log').read_text()
        unchanged=hashes=={str(s.relative_to(source_root)):sha(s) for s in dependencies}
        build={'returncode':rc,'command':list(map(str,args)),'source_root':str(source_root),'runner_sha256':sha(Path(__file__)),'source_sha256':hashes,'sources_unchanged_during_build':unchanged,'warnings':{w:txt.count('%Warning-'+w+':') for w in sorted(set(re.findall(r'%Warning-([^:]+):',txt)))},'test_config_overrides':{'dut.OPERAND_CACHE_ENABLE':1,'dut.u_npu_top.cfg_operand_fetch64':1,'SIZE':16,'ENABLE_CLOCK_GATING':1}}
        manifest.write_text(json.dumps(build,indent=2)+'\n')
        if rc or not unchanged:print(txt[-7000:]);return 1
    else:
        existing=a.reuse_build_root.resolve() if a.reuse_build_root else out
        build=json.loads((existing/'build.json').read_text())
        if build.get('returncode') or not build.get('sources_unchanged_during_build'):raise RuntimeError('cached build was not successful/stable')
        binary=existing/'obj/Vtb_operand_drain'
        if existing!=out:shutil.copy2(existing/'build.json',manifest)
        if build['source_sha256']!=hashes:raise RuntimeError('stale executable: sources changed')
    args=[binary,'+NO_RANDOM_WAIT']
    rc=command(args,out/'run.log',120);txt=(out/'run.log').read_text();print(txt,flush=True)
    marker='OPERAND_DRAIN_PASS'
    passed=rc==0 and marker in txt
    result={'passed':passed,'returncode':rc,'source_manifest_sha256':sha(manifest),'binary_sha256':sha(binary),'log_sha256':sha(out/'run.log'),'observations':[s for s in txt.splitlines() if s.startswith('OPERAND_DRAIN_')],'scope':'Real AXI-Lite clock-gated core, optional operand cache enabled by a top-level parameter, held last 12 beats of wide input allocation; after drain real IS Conv then changed-data GEMM.'}
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n');return 0 if passed else 1
if __name__=='__main__':sys.exit(main())
