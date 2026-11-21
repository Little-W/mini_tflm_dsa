#!/usr/bin/env python3
"""检查有效通道数及通道掩码的全部更新和实际源码归纳关系。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys

REL=Path('rtl/npu/conv/vector_engine.sv')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log):
    with log.open('w') as stream:
        result=subprocess.run(list(map(str,command)),stdout=stream,stderr=subprocess.STDOUT,timeout=180)
    if result.returncode:raise RuntimeError(str(log))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source-root','reference-root','tool-root','out'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--iverilog',default='iverilog')
    parser.add_argument('--vvp',default='vvp')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    text=(args.source_root/REL).read_text();reference=(args.reference_root/REL).read_text()
    start=reference.index('      taps<=0;')
    end=reference.index('`ifdef NPU_SIM_ASSERT',start)
    original=re.findall(r'(?<!\w)active\s*<=\s*([^;]+);',reference[start:end])
    selected=re.findall(r'\{active_lane_mask,active\}\s*<=\s*active_count_value\(([^;]+)\);',text)
    assert len(original)==len(selected)==4
    assert [re.sub(r'\s+','',v)for v in original]==[re.sub(r'\s+','',v)for v in selected]
    function=re.search(r'function automatic logic \[ACTIVE_COUNT_W\+TILE-1:0\] active_count_value.*?endfunction',text,re.S)[0]
    actual=text.replace('  output logic ready, done_valid,','  output logic formal_property,\n  output logic ready, done_valid,',1)
    actual=actual.replace('endmodule','''
  wire [TILE-1:0] formal_groups;
  for(genvar group=0;group<TILE;group++)begin:g_formal_group
    assign formal_groups[group]=(32'(group)<active);
  end
  assign formal_property=(formal_groups==active_lane_mask);
endmodule
''',1)
    implementation=out/'actual.sv';implementation.write_text(actual)
    case=json.loads((args.tool_root/'test/vector_engine/production_synthesis_cases.json').read_text())['vector']
    sources=list(dict.fromkeys([Path(p)for p in case['sources']]+[p.relative_to(args.source_root)for p in sorted((args.source_root/'rtl/common').rglob('*'))if p.suffix in('.v','.sv')]))
    worker=[sys.executable,args.tool_root/'scripts/fpga/open_fpga_synth.py','--worker']
    profiles=[]
    parameters=((16,8,True),(16,16,False),(4,1,False),(7,3,False),(32,8,True),(64,16,True))
    for tile,pe,fpga in parameters:
        folder=out/f't{tile}_p{pe}_f{int(fpga)}';folder.mkdir(exist_ok=True)
        arguments=['read_slang','--top','vector_engine','-D','SYNTHESIS=1','-D','XILINX_FPGA=1'if fpga else'ASIC_SYNTHESIS=1',
                   f'-GTILE={tile}',f'-GPE_COUNT={pe}',
                   f'-GSHARED_STORAGE_ENABLE={int(tile==16 and pe==8)}',
                   f'-GSHARED_QUANT_ENABLE={int(tile==16 and pe==16)}',
                   f'-GBUS_WIDTH={64 if tile==16 and pe==8 else 32}',
                   f'-GWINDOW_LANES={8 if tile==16 and pe==8 else 4}',
                   '-I',str(args.source_root/'include'),'-I',str(args.source_root/'rtl/npu/ps_compact')]
        arguments += [str(implementation if p==REL else args.source_root/p)for p in sources]
        script=folder/'elaborate.ys'
        script.write_text(shlex.join(arguments)+'\n'
                          'read_verilog -lib -overwrite +/xilinx/cells_sim.v\nread_verilog -lib -overwrite +/xilinx/cells_xtra.v\n'
                          'hierarchy -top vector_engine\nproc\nflatten\nopt -keepdc\nselect vector_engine\n'
                          'write_json -selected '+str(folder/'flat.json')+'\n')
        run(worker+[script],folder/'elaborate.log')
        design=json.loads((folder/'flat.json').read_text());module=design['modules']['vector_engine']
        kept=('active','active_lane_mask')
        bits={b for name in kept for b in module['netnames'][name]['bits']}
        ports={name:v for name,v in module['ports'].items()if v['direction']=='input'or name=='formal_property'}
        retained=[];free=[]
        for name,cell in list(module['cells'].items()):
            if not any(k in cell['type']for k in('dff','latch'))and not cell['type'].startswith('$mem'):continue
            outputs=[b for port,d in cell['port_directions'].items()if d=='output'for b in cell['connections'][port]]
            if any(b in bits for b in outputs):
                assert all(b in bits for b in outputs);retained.append(name);continue
            del module['cells'][name]
            for port,direction in cell['port_directions'].items():
                if direction!='output':continue
                outputs=cell['connections'][port]
                if not any(isinstance(b,int)for b in outputs):continue
                label='abstract_'+str(len(free));ports[label]={'direction':'input','bits':outputs};free.append(name)
        module['ports']=ports;module['memories']={}
        for name in kept:ports['o_'+name]={'direction':'output','bits':module['netnames'][name]['bits']}
        for net in module['netnames'].values():net['attributes'].pop('init',None)
        assert len(retained)==2
        (folder/'abstract.json').write_text(json.dumps(design))
        script=folder/'prove.ys'
        script.write_text('read_json '+str(folder/'abstract.json')+'\n'
                          'hierarchy -top vector_engine\nopt -full\nasync2sync\nopt -full\n'
                          'sat -verify -tempinduct -seq 4 -set-at 1 rst_n 0 -prove formal_property 1 '
                          '-show o_active,o_active_lane_mask\n')
        log=folder/'prove.log';run(worker+[script],log)
        log_text=log.read_text();assert'Induction step proven: SUCCESS!'in log_text
        profiles.append({'tile':tile,'pe':pe,'fpga':fpga,'shared_storage':tile==16 and pe==8,
                         'shared_quant':tile==16 and pe==16,'bus_width':64 if tile==16 and pe==8 else 32,
                         'window_lanes':8 if tile==16 and pe==8 else 4,'passed':True,
                         'induction_length':int(re.findall(r'Trying induction with length (\d+)',log_text)[-1]),
                         'retained_registers':kept,'free_register_outputs':len(free),'log_sha256':sha(log)})
        for name in('flat.json','abstract.json'):(folder/name).unlink()
    model=out/'four_state.sv'
    model_text='''module group_model #(parameter integer TILE=16,PE_COUNT=8,
 ACTIVE_COUNT_W=$clog2(TILE+1))(
 input logic clk,rst_n,load,input logic [ACTIVE_COUNT_W-1:0] next_index,
 output logic identical
);
 logic [ACTIVE_COUNT_W-1:0] original_index,selected_index;
 logic [TILE-1:0] selected_groups,expected_groups;
'''+function+'''
 always @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin original_index<=0;{selected_groups,selected_index}<=active_count_value(0);end
  else if(load)begin original_index<=next_index;{selected_groups,selected_index}<=active_count_value(next_index);end
 end
 for(genvar group=0;group<TILE;group++)assign expected_groups[group]=(32'(group)<original_index);
 assign identical=({original_index,expected_groups}==={selected_index,selected_groups});
endmodule
module tb;
 logic clk=0,rst_n=0,load=0;
 logic [7:0] index;
 wire [5:0] identical;
 integer i,j,checks=0;
 integer unsigned rng=32'h13729d47;
 function automatic integer unsigned random_next;
  rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);return rng;
 endfunction
 function automatic logic four(input logic[1:0] value);
  case(value)0:four=0;1:four=1;2:four=1'bx;3:four=1'bz;endcase
 endfunction
 task tick;
  #1;clk=1;#1;if(identical!==6'h3f)$fatal(1,"有效通道数与通道掩码关系不一致");clk=0;checks+=6;
 endtask
'''
    for i,(tile,pe,_)in enumerate(parameters):
        width=tile.bit_length()
        model_text+=f'group_model #(.TILE({tile}),.PE_COUNT({pe})) g{i}(clk,rst_n,load,index[{width-1}:0],identical[{i}]);\n'
    model_text+='''initial begin
 tick();rst_n=1;
 for(i=0;i<65536;i++)begin
  for(j=0;j<8;j++)index[j]=four(2'(i>>(2*j)));
  load=four(2'(random_next()));if(i%101==0)rst_n=four(2'(random_next()));else rst_n=1;
  tick();
 end
 $display("ACTIVE_CHANNEL_MASK_PASS comparisons=%0d",checks);$finish;
end
endmodule
'''
    model.write_text(model_text)
    executable=out/'four_state.vvp'
    run([args.iverilog,'-g2012','-s','tb','-o',executable,model],out/'compile.log')
    run([args.vvp,executable],out/'four_state.log')
    report={'passed':True,'source_sha256':sha(args.source_root/REL),'reference_sha256':sha(args.reference_root/REL),
            'update_sites':4,'profiles':profiles,'four_state_comparisons':393222,
            'constraints':'First sampled cycle reset; all other inputs and subsequent resets free',
            'test_sha256':sha(Path(__file__)),'four_state_log_sha256':sha(out/'four_state.log')}
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':main()
