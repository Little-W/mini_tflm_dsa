#!/usr/bin/env python3
"""证明配置核尺寸资格在原有乘积阶段内保存的关系。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys

REL = Path('rtl/npu/conv/vector_config_check.sv')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log):
    with log.open('w') as stream:
        result = subprocess.run(list(map(str, command)), stdout=stream,
                                stderr=subprocess.STDOUT, timeout=120)
    if result.returncode:
        raise RuntimeError(str(log))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-root', 'reference-root', 'tool-root', 'out'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    text = (args.source_root/REL).read_text()
    original = (args.reference_root/REL).read_text()
    recovered = text.replace('  logic kernel_limit_ok_q;\n', '')
    recovered = recovered.replace('(kernel_limit_ok_q &&',
                                  "(kernel_count <= 32'(depthwise ? MAX_TAPS : POOL_MAX_TAPS) &&", 1)
    recovered = recovered.replace('      kernel_limit_ok_q<=0;\n', '')
    recovered = recovered.replace('''        // 核尺寸乘积已在前一阶段保存，提前记录配置上限检查结果。
        if (phase==3'd1) kernel_limit_ok_q <= (kernel_count <= 32'(depthwise ? MAX_TAPS : POOL_MAX_TAPS));
''', '')
    assert recovered == original
    actual = text.replace('  output logic ready,done,error,',
                          '  output logic formal_property,\n  output logic ready,done,error,', 1)
    actual = actual.replace('endmodule', '''
  logic [3:0] formal_previous_op;
  always_ff @(posedge clk) begin
    formal_previous_op <= cfg.op;
  end
  always_comb if (rst_n && state != IDLE && state != COMPLETE) assume(cfg.op == formal_previous_op);
  wire formal_required = (state == CALCULATE && phase >= 3'd2) ||
      (state == CAPTURE && phase >= 3'd1) || (state == FIELDS && spatial);
  assign formal_property = !formal_required ||
      (kernel_limit_ok_q == (kernel_count <= 32'(depthwise ? MAX_TAPS : POOL_MAX_TAPS)));
endmodule
''', 1)
    implementation = out/'actual.sv'
    implementation.write_text(actual)
    deps = [args.source_root/'rtl/npu/conv'/n for n in ('conv_im2col_pkg.sv', 'vector_engine_pkg.sv')]
    deps += [args.source_root/'rtl/common/parallel_prefix_add.sv']
    worker = [sys.executable, args.tool_root/'scripts/fpga/open_fpga_synth.py', '--worker']
    profiles = []
    for tile, max_taps, pool_max, fpga in ((16,49,256,True),(16,49,256,False),
            (2,1,1,False),(4,7,31,False),(64,49,1024,True),(16,255,65535,True)):
        folder = out/f't{tile}_m{max_taps}_p{pool_max}_f{int(fpga)}'
        folder.mkdir(exist_ok=True)
        arguments = ['read_slang', '--top', 'vector_config_check', '-D', 'SYNTHESIS=1',
                     '-D', 'XILINX_FPGA=1' if fpga else 'ASIC_SYNTHESIS=1',
                     f'-GTILE={tile}', f'-GMAX_TAPS={max_taps}', f'-GPOOL_MAX_TAPS={pool_max}']
        script = folder/'elaborate.ys'
        script.write_text(shlex.join(arguments+list(map(str,deps+[implementation])))+'\n'
                          'hierarchy -top vector_config_check\nproc\nflatten\nopt -keepdc\n'
                          'write_json '+str(folder/'flat.json')+'\n')
        run(worker+[script],folder/'elaborate.log')
        design=json.loads((folder/'flat.json').read_text());module=design['modules']['vector_config_check']
        kept=('state','phase','kernel_count','kernel_limit_ok_q','formal_previous_op')
        bits={bit for name in kept for bit in module['netnames'][name]['bits']}
        ports={name:value for name,value in module['ports'].items()
               if value['direction']=='input' or name=='formal_property'}
        retained=[];free=[]
        for name,cell in list(module['cells'].items()):
            if not any(k in cell['type'] for k in ('dff','latch')):
                continue
            outputs=[b for port,direction in cell['port_directions'].items()
                     if direction=='output' for b in cell['connections'][port]]
            if any(b in bits for b in outputs):
                assert all(b in bits for b in outputs)
                retained.append(name);continue
            del module['cells'][name]
            for port,direction in cell['port_directions'].items():
                if direction!='output':continue
                outputs=cell['connections'][port];label='abstract_'+str(len(free))
                ports[label]={'direction':'input','bits':outputs}
                free.append({'name':name,'port':port,'bits':outputs})
        module['ports']=ports
        for name in kept:
            ports['o_'+name]={'direction':'output','bits':module['netnames'][name]['bits']}
        for net in module['netnames'].values():net['attributes'].pop('init',None)
        (folder/'abstract.json').write_text(json.dumps(design))
        script=folder/'prove.ys'
        script.write_text('read_json '+str(folder/'abstract.json')+'\n'
                          'hierarchy -top vector_config_check\nopt -full\nasync2sync\nopt -full\n'
                          'sat -verify -tempinduct -seq 4 -set-assumes -set-at 1 rst_n 0 '
                          '-prove formal_property 1 -show o_state,o_phase,o_kernel_count,o_kernel_limit_ok_q\n')
        log=folder/'prove.log';run(worker+[script],log)
        log_text=log.read_text();assert 'Induction step proven: SUCCESS!' in log_text
        profiles.append({'tile':tile,'max_taps':max_taps,'pool_max_taps':pool_max,'fpga':fpga,
                         'passed':True,'induction_length':int(re.findall(r'Trying induction with length (\d+)',log_text)[-1]),
                         'retained_registers':kept,'free_register_outputs':len(free),'log_sha256':sha(log)})
        for name in ('flat.json','abstract.json'):(folder/name).unlink()
    report={'passed':True,'source_sha256':sha(args.source_root/REL),'reference_sha256':sha(args.reference_root/REL),
            'source_audit':'Only kernel_limit_ok_q capture and its FIELDS use differ',
            'assumptions':'First sampled cycle reset; cfg.op held during checking states; freely changes in IDLE and COMPLETE; all other inputs and later resets free',
            'profiles':profiles,'test_sha256':sha(Path(__file__)),
            'dependencies_sha256':{str(p.relative_to(args.source_root)):sha(p)for p in deps}}
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':
    main()
