#!/usr/bin/env python3
"""比较普通请求流水级的全部输出和状态，并检查四态写入与保存。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execute(command, log):
    with log.open('w') as output:
        subprocess.run(list(map(str, command)), stdout=output,
                       stderr=subprocess.STDOUT, check=True, timeout=240)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    rtl = ROOT/'rtl/npu/conv/conv_im2col_request_pipeline.sv'
    text = rtl.read_text()
    header = text[text.index('module '):text.index(');')+2]
    header = header.replace('module conv_im2col_request_pipeline',
                            'module conv_im2col_request_pipeline_reference')
    reference = out/'reference.sv'
    reference.write_text('// 同步请求字段的逐周期参考模型。\n'+header+'''
  logic capture_ready, preview_next;
  assign capture_ready = !o_pending || i_cache_ready || i_cancel;
  assign o_request_valid = i_request_valid && !i_error;
  assign o_request_ready = p_registered ? capture_ready : i_cache_ready;
  assign o_capture_ready = capture_ready;
  assign o_cache_valid = p_registered ? o_pending && !i_cancel : o_request_valid;
  always_comb begin
    preview_next = p_registered && o_request_valid && o_request_ready;
    case (o_request_ready)
      1'b1: preview_next = p_registered;
      default: begin end
    endcase
  end
  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) begin
      o_pending <= 1'b0;
      o_preview_valid <= 1'b0;
    end else begin
      o_preview_valid <= preview_next;
      if (o_request_ready) o_pending <= p_registered && o_request_valid;
    end
  end
  always_ff @(posedge i_clk) begin
    if (capture_ready) begin
      o_address <= i_address;
      o_index_valid <= i_index_valid;
      o_geometry <= i_geometry;
      o_event_first <= i_event_first;
      o_epoch <= i_epoch;
      o_y <= i_y;
      o_progress <= i_progress;
    end
  end
  conv_request_index_register u_request_index_register (
    .i_clk, .i_write(capture_ready), .i_pixel, .i_short_pixel,
    .i_shift(i_index_shift), .i_reference(i_index_reference), .o_index
  );
endmodule
''')
    sources = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies'](
        [ROOT/'rtl/npu/conv/conv_im2col_pkg.sv', rtl, reference], ROOT)
    hashes = {str(p):digest(p) for p in sources}
    report = dict(input_constraints=[],disabled_lookahead_outputs_and_state=True,
                  source_sha256=hashes, formal=[], four_state=[])
    for mode, flags in [('generic', ['-USYNTHESIS','-UXILINX_FPGA']),
                        ('fpga', ['-DSYNTHESIS=1','-DXILINX_FPGA=1'])]:
        for registered in (0,1):
            for shift in (3,4):
                name = f'{mode}_registered{registered}_shift{shift}'
                options = [*flags,f'-Gp_registered={registered}',f'-Gp_word_shift={shift}',
                           '-Gp_lookahead=0']
                commands=[]
                for label, top in [('reference','conv_im2col_request_pipeline_reference'),
                                   ('current','conv_im2col_request_pipeline')]:
                    commands += ['read_slang --top '+top+' '+shlex.join(options+list(map(str,sources))),
                        'setattr -mod -unset keep_hierarchy','setattr -unset keep_hierarchy',
                        'prep -top '+top+' -flatten','async2sync','opt -full',
                        'rename -top '+label,'design -stash '+label]
                commands += ['design -copy-from reference -as reference reference',
                    'design -copy-from current -as current current','equiv_make reference current proof',
                    'hierarchy -top proof','opt -full','equiv_simple -seq 1','equiv_induct -seq 3',
                    'equiv_simple -seq 1','opt_clean','equiv_status -assert']
                script=out/(name+'.ys');log=out/(name+'.log')
                script.write_text('\n'.join(commands)+'\n')
                execute([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],log)
                counts=re.findall(r'Found (\d+) \$equiv cells',log.read_text())
                assert counts and 'Equivalence successfully proven!' in log.read_text()
                report['formal'].append(dict(mode=mode,registered=registered,word_shift=shift,
                    passed=True,bits=int(counts[-1]),log_sha256=digest(log)))
                print('REQUEST_PIPELINE_FORMAL_PASS '+name,flush=True)
    port_file=out/'ports.json';script=out/'ports.ys'
    script.write_text('read_slang --top conv_im2col_request_pipeline '+shlex.join(list(map(str,sources)))+
        '\nwrite_json '+str(port_file)+'\n')
    execute([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],out/'ports.log')
    ports=json.loads(port_file.read_text())['modules']['conv_im2col_request_pipeline']['ports']
    inputs={name:len(value['bits']) for name,value in ports.items()
            if value['direction']=='input' and name not in ('i_clk','i_rst_n')}
    outputs={name:len(value['bits']) for name,value in ports.items() if value['direction']=='output'}
    input_width=sum(inputs.values());output_width=sum(outputs.values())
    assert input_width>0 and output_width>0 and all(inputs.values()) and all(outputs.values())
    common='\n'.join(f'  wire [{width-1}:0] {name};' for name,width in inputs.items())
    connections=','.join('.'+name+'('+name+')' for name in inputs)
    instances=[]
    for registered in (0,1):
        for label,top in [('actual','conv_im2col_request_pipeline'),
                          ('expected','conv_im2col_request_pipeline_reference')]:
            declarations='\n'.join(f'  wire [{width-1}:0] {label}_{registered}_{name};'
                                   for name,width in outputs.items())
            connect=','.join('.'+name+'('+label+'_'+str(registered)+'_'+name+')' for name in outputs)
            instances.append(declarations+'\n  '+top+f' #(.p_registered({registered}),.p_lookahead(0)) u_{label}_{registered}('
                '.i_clk(clk),.i_rst_n(rst_n),'+connections+','+connect+');')
    comparisons='\n'.join('      if ({'+','.join('actual_'+str(r)+'_'+n for n in outputs)+'} !== {'+
        ','.join('expected_'+str(r)+'_'+n for n in outputs)+'}) $fatal(1,"REQUEST_PIPELINE_MISMATCH registered='+str(r)+' sample=%0d",sample);'
        for r in (0,1))
    bench=out/'tb.sv'
    bench.write_text('''// 逐周期比较未知输入、写入停顿以及复位后的全部公开字段。
module tb;
  logic clk=0, rst_n=1;
'''+f'  localparam int p_input_width={input_width};\n'+common+'''
  logic [p_input_width-1:0] stimulus;
  bit [p_input_width-1:0] seen_zero='0,seen_one='0,seen_x='0,seen_z='0;
  int unsigned random_state=32'h384ac2e1;
'''+ '  assign {'+','.join(inputs)+'} = stimulus;\n'+'\n'.join(instances)+'''
  function automatic int unsigned random_word;
    random_state^=random_state<<13;
    random_state^=random_state>>17;
    random_state^=random_state<<5;
    return random_state;
  endfunction
  initial begin
    stimulus='0;
    #1;rst_n=0;#1;clk=1;#1;clk=0;rst_n=1;
    for (integer sample=0;sample<4096;sample++) begin
      for(integer bit_index=0;bit_index<p_input_width;bit_index++)
        stimulus[bit_index]=1'(random_word());
      case(sample%16)
        0:stimulus='0;
        1:stimulus='1;
        2:stimulus='x;
        3:stimulus='z;
        4,5,6,7:stimulus[sample%p_input_width]=1'bx;
        8,9,10,11:stimulus[sample%p_input_width]=1'bz;
        default:begin end
      endcase
      for(integer bit_index=0;bit_index<p_input_width;bit_index++)
        case(stimulus[bit_index])
          1'b0:seen_zero[bit_index]=1;
          1'b1:seen_one[bit_index]=1;
          1'bx:seen_x[bit_index]=1;
          default:seen_z[bit_index]=1;
        endcase
      #1;clk=1;#1;
'''+comparisons+'''
      clk=0;
    end
    if(!(&seen_zero) || !(&seen_one) || !(&seen_x) || !(&seen_z))
      $fatal(1,"REQUEST_PIPELINE_INPUT_COVERAGE");
    $display("REQUEST_PIPELINE_FOUR_STATE_PASS samples=4096 registers=2 input_bits=%0d",p_input_width);
    $finish;
  end
endmodule
''')
    for mode,flags in [('generic',[]),('fpga',['-DXILINX_FPGA=1']),
                       ('synthesis',['-DSYNTHESIS=1','-DXILINX_FPGA=1'])]:
        executable=out/(mode+'.vvp');log=out/(mode+'_four_state.log')
        execute(['iverilog','-g2012',*flags,'-s','tb','-o',executable,*sources,bench],out/(mode+'_build.log'))
        execute(['vvp',executable],log)
        assert 'REQUEST_PIPELINE_FOUR_STATE_PASS' in log.read_text()
        report['four_state'].append(dict(mode=mode,passed=True,samples=4096,registered_variants=2,
            input_bits=input_width,output_bits=output_width,every_input_bit_all_four_states=True,
            log_sha256=digest(log)))
        print('REQUEST_PIPELINE_FOUR_STATE_PASS '+mode,flush=True)
    assert all(digest(p)==expected for p,expected in hashes.items())
    report['passed']=True
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    main()
