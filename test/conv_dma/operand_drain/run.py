#!/usr/bin/env python3
"""Verify retirement after a held prefetch suffix on current production RTL."""
from pathlib import Path
import argparse,hashlib,json,re,shutil,subprocess,sys
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'scripts/rtl'))
from source_files import input_files, with_dependencies
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def command(args,log,timeout=1200):
    with log.open('w') as f:
        f.write('COMMAND: '+repr([str(a) for a in args])+'\n');f.flush()
        return subprocess.run(list(map(str,args)),cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,timeout=timeout).returncode
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,default=ROOT/'build/conv_dma/operand_drain')
    p.add_argument('--source-root',type=Path,default=ROOT,help='待验证 RTL 所在目录')
    p.add_argument('--verilator',default='verilator');p.add_argument('--jobs',type=int,default=2)
    p.add_argument('--skip-build',action='store_true')
    p.add_argument('--lint-only',action='store_true')
    p.add_argument('--reuse-build-root',type=Path,help='Optional compiled profile; every source/include hash must match')
    a=p.parse_args()
    if a.skip_build and a.lint_only:p.error('--lint-only 与 --skip-build 不能同时使用')
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    source_root=a.source_root.resolve()
    npu=source_root/'rtl/npu';packages=[npu/'conv/conv_im2col_pkg.sv',npu/'conv/vector_engine_pkg.sv']
    sources=packages+[s for s in sorted(npu.rglob('*.sv')) if s not in packages]+sorted(npu.rglob('*.v'))
    sources += [source_root/'rtl/common'/name for name in
                ('regfile.v','onehot_check.sv','add_equal.sv','add3_equal.sv','parallel_prefix_add.sv')]
    sources+=[source_root/'rtl/common/pseudo_dual_port_ram.v',source_root/'rtl/axi_top/npu_axil_top.sv',source_root/'rtl/axi_top/npu_axil_reg_if.sv',ROOT/'test/conv_npu/axi_memory.sv',HERE/'tb_operand_drain.sv']
    sources.append(ROOT/'test/monitors/requant_group_buffer_observer.sv')
    sources=with_dependencies(sources,source_root)
    config=ROOT/'test/conv_npu/simulator.vlt'
    dependencies=input_files(sources+[config,Path(__file__),ROOT/'scripts/rtl/source_files.py'],source_root)
    def dependency_name(path):
        return str(path.relative_to(source_root) if path.is_relative_to(source_root) else path.relative_to(ROOT))
    hashes={dependency_name(s):sha(s) for s in dependencies}
    manifest=out/'build.json';binary=out/'obj/Vtb_operand_drain'
    if not a.skip_build:
        args=[a.verilator,'--lint-only' if a.lint_only else '--binary','--timing','--assert','-sv','--top-module','tb_operand_drain','-Wno-fatal','--output-groups','0','--output-split','10000','--output-split-cfuncs','1000',f'-I{source_root/"include"}',f'-I{npu/"ps_compact"}',
            '-DGEMPACT_PS_COMPRESS=1','-DGEMMORA_PS_POOL_BYTES=49152','-DGEMMORA_PS_FORCE_RAW=1',
            '--Mdir',out/'obj','-j',a.jobs,'-CFLAGS','-std=c++20 -O1','-MAKEFLAGS','OPT_FAST=-O1 OPT_SLOW=-O0',config,*sources]
        rc=command(args,out/'build.log');txt=(out/'build.log').read_text()
        unchanged=hashes=={dependency_name(s):sha(s) for s in dependencies}
        build={'returncode':rc,'command':list(map(str,args)),'source_root':str(source_root),'runner_sha256':sha(Path(__file__)),'source_sha256':hashes,'sources_unchanged_during_build':unchanged,'warnings':{w:txt.count('%Warning-'+w+':') for w in sorted(set(re.findall(r'%Warning-([^:]+):',txt)))},'test_config_overrides':{'dut.OPERAND_CACHE_ENABLE':1,'dut.u_npu_top.cfg_operand_fetch64':1,'SIZE':16,'ENABLE_CLOCK_GATING':1,'SHARED_BANK_BYTES':8192,'SHARED_BANK_COUNT':7},'lint_only':a.lint_only}
        manifest.write_text(json.dumps(build,indent=2)+'\n')
        if rc or not unchanged:print(txt[-7000:]);return 1
        if a.lint_only:return 0
    else:
        existing=a.reuse_build_root.resolve() if a.reuse_build_root else out
        build=json.loads((existing/'build.json').read_text())
        if build.get('returncode') or build.get('lint_only') or not build.get('sources_unchanged_during_build'):raise RuntimeError('cached build was not successful/stable')
        binary=existing/'obj/Vtb_operand_drain'
        if existing!=out:shutil.copy2(existing/'build.json',manifest)
        if build['source_sha256']!=hashes:raise RuntimeError('stale executable: sources changed')
    args=[binary,'+NO_RANDOM_WAIT']
    rc=command(args,out/'run.log',120);txt=(out/'run.log').read_text();print(txt,flush=True)
    marker='OPERAND_DRAIN_PASS'
    passed=rc==0 and marker in txt
    result={'passed':passed,'returncode':rc,'source_manifest_sha256':sha(manifest),'binary_sha256':sha(binary),'log_sha256':sha(out/'run.log'),'observations':[s for s in txt.splitlines() if s.startswith('OPERAND_DRAIN_')],'scope':'真实 AXI-Lite 门控内核，启用操作数缓存，保持宽突发的最后12拍；排空后执行IS Conv与更新数据的GEMM。真实完成事件背压3周期后同时注入完成接受与故障，检查正常完成被禁止、错误完成及后续GEMM恢复。'}
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n');return 0 if passed else 1
if __name__=='__main__':sys.exit(main())
