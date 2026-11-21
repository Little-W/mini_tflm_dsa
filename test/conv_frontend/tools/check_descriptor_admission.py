#!/usr/bin/env python3
"""检查描述符接收阶段、直接模式行为及接收时的数据字选择。"""
import argparse,hashlib,json,runpy,shlex,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
p=argparse.ArgumentParser();p.add_argument('--source-root',type=Path,required=True);p.add_argument('--reference-root',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
e=runpy.run_path(str(ROOT/'test/conv_frontend/tools/check_frontend_event_domains.py'));paths=[r/'rtl/npu/conv/conv_im2col_frontend.sv'for r in(a.source_root,a.reference_root)];hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in paths}
def module(text,name):
 body=e['module'](text,name).replace('output logic invariant);','output logic invariant,output logic captured,ready,idle,forward_agrees);')
 if 'logic descriptor_response_forward;' not in body:
  body=body.replace(' st_t state;',' logic descriptor_response_forward;\n st_t state;')
 if 'assign descriptor_response_forward'not in body:
  body=body.replace(' assign result=', ' assign descriptor_response_forward=finishing_tile&&state[$clog2(WAIT_WORD)];\n assign result=')
 body=body.replace('endmodule','''assign captured=tile_capture;
 assign ready=tile_ready;
 assign idle=state[$clog2(IDLE)];
 assign forward_agrees=!tile_capture ||
   descriptor_response_forward==(finishing_tile&&state[$clog2(WAIT_WORD)]);
endmodule''')
 return body
pair=module(paths[0].read_text(),'current')+module(paths[1].read_text(),'reference');rows=[]
for registered in (0,1):
 sv=a.out/f'reg{registered}.sv';ys=a.out/f'reg{registered}.ys';log=a.out/f'reg{registered}.log'
 sv.write_text(pair+f'''module proof({e['PORTS']}output logic equivalent);
 logic[20:0]current_result,reference_result;
 logic ci,ri,cc,rc,cr,rr,cd,rd,cf,rf;
 current #(.REGISTER_DESCRIPTOR({registered}))u_current(.*,.result(current_result),.invariant(ci),.captured(cc),.ready(cr),.idle(cd),.forward_agrees(cf));
 reference #(.REGISTER_DESCRIPTOR({registered}))u_reference(.*,.result(reference_result),.invariant(ri),.captured(rc),.ready(rr),.idle(rd),.forward_agrees(rf));
 assign equivalent=ci&&ri&&cf&&rf&&(current_result==reference_result)&&
    ({registered} ? ((!cc||cd)&&(cd?(cr==rr):!cr)) : ((cr==rr)&&(cc==rc)));
endmodule
''')
 ys.write_text('read_slang --top proof -DSYNTHESIS=1 -DXILINX_FPGA=1 '+shlex.quote(str(sv))+'\nprep -top proof -flatten\ncheck -assert\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
 with log.open('w')as f:r=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(ys)],stdout=f,stderr=subprocess.STDOUT,timeout=120)
 if r.returncode or'SUCCESS!'not in log.read_text():raise RuntimeError(str(log))
 rows.append({'registered_descriptor':registered,'passed':True,'source_sha256':hashlib.sha256(sv.read_bytes()).hexdigest(),'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in paths}
report={'passed':True,'source_sha256':hashes,'runs':rows,'input_constraints':[],'state_encoding':'One-hot or zero, consistent with the unchanged reset and state assignments.','properties':['Both modes preserve the 21 execution-update event results.','Direct descriptor mode preserves acceptance and ready for all inputs.','Registered descriptor mode accepts only in IDLE and preserves ready within IDLE.','Every accepted descriptor uses the same data-word forwarding source as the reference.']};(a.out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(report)
