#!/usr/bin/env python3
"""从复位证明完整缓存的预读身份、接收资格及未处理请求的保存性质。"""
from pathlib import Path
import argparse
import hashlib
import json
import runpy
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
CACHE=Path('rtl/npu/dma/cache/conv_windowed_cache.sv')
PROPERTIES='''
  always_comb begin
    assert (!u_request_path.preview_selected_q || clearing ||
        work_request.in_range == (work_request.address >= base_q && work_request.address < end_q));
    assert (!preview_active || work_request.in_range == incoming_request.in_range);
    assert (!preview_active || work_request.address == incoming_request.address);
    assert (!preview_active || work_request.set_index == incoming_request.set_index);
    assert (!preview_active || accepted_request);
    assert (!(request_push && request_count == 0) || u_request_path.lookup_read_request == incoming_request);
  end
'''
RESPONSE_PROPERTIES='''
  always_comb begin
    assert (rsp_valid == (response_count != 0));
    assert (rsp_data == u_request_path.saved_response_data);
    assert (rsp_error == u_request_path.saved_response_error);
    assert (response_push == (u_request_path.core_rsp_valid && core_rsp_ready));
    assert (consumed_response == response_pop);
    assert (rsp_success == (rsp_valid && !rsp_error));
    assert (rsp_failure == (rsp_valid && rsp_error));
    assert (core_rsp_ready == (response_count < DQ_CW'(DEMAND_DEPTH) || response_pop));
  end
'''


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--response-properties',action=argparse.BooleanOptionalAction,default=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    source_root=args.source_root.resolve()
    original=(source_root/CACHE).read_text();assert original.count('endmodule')==1
    modified=out/'conv_windowed_cache.sv'
    properties=PROPERTIES+(RESPONSE_PROPERTIES if args.response_properties else '')
    modified.write_text(original.replace('endmodule',properties+'\nendmodule'))
    resolver=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources=resolver([modified],source_root);hashes={str(p):digest(p) for p in sources}
    results=[]
    for mode,flags in (('generic',['-USYNTHESIS','-UXILINX_FPGA']),('fpga',['-DSYNTHESIS=1','-DXILINX_FPGA=1'])):
        for depth in (2,4):
            script=out/f'{mode}_{depth}.ys';log=out/f'{mode}_{depth}.log'
            commands=['read_slang --top conv_windowed_cache '+shlex.join(flags+[
                '-GSETS=2','-GWAYS=2','-GLINE_BYTES=16','-GBUS_WIDTH=32','-GREAD_WIDTH=32',
                f'-GDEMAND_DEPTH={depth}','-Gp_preview_request=1']+list(map(str,sources))),
                'setattr -mod -unset keep_hierarchy','setattr -unset keep_hierarchy','setattr -unset keep',
                'prep -top conv_windowed_cache -flatten','delete -output conv_windowed_cache/w:*',
                'memory_map','async2sync','chformal -lower','opt -full','dffunmap','opt_clean -purge',
                'sat -seq 2 -set-at 1 rst_n 0 -prove-asserts -verify -timeout 45',
                'sat -seq 2 -tempinduct -tempinduct-inductonly -maxsteps 5 -prove-asserts -verify -timeout 45']
            script.write_text('\n'.join(commands)+'\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],
                    check=True,stdout=stream,stderr=subprocess.STDOUT,timeout=180)
            text=log.read_text();assert 'SUCCESS!' in text and 'Induction step proven' in text
            result=dict(mode=mode,depth=depth,passed=True,log_sha256=digest(log))
            results.append(result);print(json.dumps(result),flush=True)
    assert all(digest(p)==h for p,h in hashes.items())
    (out/'summary.json').write_text(json.dumps(dict(passed=True,properties=14 if args.response_properties else 6,
        reset_condition='rst_n=0 at initial proof cycle',input_constraints=[],
        source_sha256=hashes,formal=results),indent=2)+'\n')


if __name__=='__main__':main()
