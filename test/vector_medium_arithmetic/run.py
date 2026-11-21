#!/usr/bin/env python3
"""检查向量配置、坐标和 AVG 算术的完整位宽及四态行为。"""
from __future__ import annotations
import argparse, hashlib, json, re, shlex, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
ENGINE = Path('rtl/npu/conv/vector_engine.sv')
CHECKER = Path('rtl/npu/conv/vector_config_check.sv')
PROFILES = ((4, 1), (16, 49), (16, 256), (64, 65535))
IMAGE_FIELDS = ('input_w','input_h','dilation_w','dilation_h','stride_w','stride_h','output_w','pad_left','pad_top')
ALIASES = ('fetch_ox_next', 'ox_next', 'oy_next', 'channel_remaining',
           'dilation_x_negative', 'dilation_y_negative', 'stride_x_negative', 'stride_y_negative',
           'dilation_x_maximum', 'dilation_y_maximum', 'stride_x_maximum', 'stride_y_maximum',
           'output_last_column_next', 'padding_x_negative', 'padding_y_negative',
           'avg_negated_sum', 'avg_residual_next', 'range_output_distance', 'output_range_distance',
           'range_before_output', 'output_before_range')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assignment(source, name, operator='=', contains=None):
    prefix = r'\bassign\s+' if operator == '=' else r'(?<!\w)'
    matches = re.findall(prefix + re.escape(name) + r'\s*' + re.escape(operator) + r'\s*(.*?);', source, re.S)
    if contains is not None:
        matches = [x for x in matches if (re.search(r'\+\s*1\b', x) if contains == '+1' else contains in x)]
    assert matches, (name, contains)
    return matches[0].strip()


def definition(source, name):
    declarations = re.finditer(r'^\s*(?:\(\*[^\n]*\*\)\s*)?(?:logic|wire)\s+((?:signed\s+)?(?:\[[^;\n]+?\])?)\s*([^;=\n]+);', source, re.M)
    for match in declarations:
        if name in [x.strip() for x in match[2].split(',')]:
            return 'logic ' + match[1] + ' ' + name + ';\nassign ' + name + ' = ' + assignment(source, name) + ';\n'
    raise RuntimeError('找不到算术声明：' + name)


def model(label, engine, checker, is_candidate):
    for field in IMAGE_FIELDS:
        engine = engine.replace('c.image.' + field, 'image_' + field)
    checker = checker.replace('cfg.output_base', 'config_output_base')
    values = []
    for name in ('dilation_x', 'dilation_y', 'stride_x', 'stride_y'):
        for suffix in ('min', 'max'):
            values.append((name + '_' + suffix, 'signed [16:0]', assignment(engine, name + '_' + suffix, '<=')))
    values.append(('output_last_column', '[15:0]', assignment(engine, 'output_last_column', '<=')))
    for axis, field in (('x', 'pad_left'), ('y', 'pad_top')):
        needle = 'padding_' + axis + '_negative' if is_candidate else field
        values.append(('origin_' + axis, 'signed [33:0]', assignment(engine, 'fetch_origin_' + axis, '<=', needle)))
    for name, needle in [('fetch_ox','+1'), ('ox',"+16'd1"), ('ox','+1'), ('oy',"+16'd1"), ('oy','+1')]:
        values.append((name + str(len(values)), '[15:0]', assignment(engine, name, '<=', name + '_next' if is_candidate else needle)))
    values.append(('active', '[ACTIVE_COUNT_W-1:0]', assignment(engine, 'active', '<=', '<TILE')))
    values.append(('channel_next', '[16:0]', assignment(engine, 'channel_next_value')))
    magnitude = re.search(r'wire\s+\[POOL_SUM_WIDTH-1:0\]\s+avg_unsigned_magnitude\s*=\s*(.*?);', engine, re.S)[1]
    values.append(('avg_magnitude', '[POOL_SUM_WIDTH-1:0]', magnitude))
    values.append(('avg_residual', 'signed [AVG_SCALE_BITS+1:0]', assignment(engine, 'avg_residual_q', '<=')))
    original_ranges = ("range_end_q<={1'b0,config_output_base}", "output_end_q<={1'b0,range_base_q}")
    if not is_candidate:
        assert all(x in re.sub(r'\s+', '', checker) for x in original_ranges)
    values.append(('range_before_output', '', 'range_before_output' if is_candidate else original_ranges[0]))
    values.append(('output_before_range', '', 'output_before_range' if is_candidate else original_ranges[1]))
    definitions = ''
    if is_candidate:
        for name in ALIASES:
            definitions += definition(checker if name in ALIASES[-4:] else engine, name)
    body = f'''module native_{label} #(parameter integer TILE=16, POOL_MAX_TAPS=256)(
 input logic [15:0] {', '.join('image_'+field for field in IMAGE_FIELDS)},
 input logic [31:0] config_output_base,
 input logic [31:0] channels, range_base_q,
 input logic [32:0] range_end_q, output_end_q,
 input logic [15:0] channel_base, fetch_ox, ox, oy,
 input logic [6:0] active_input,
 input logic signed [23:0] sum_input,
 input logic [23:0] numerator_input,
 input logic [24:0] check_input,
 output wire [{64*len(values)-1}:0] value
);
 localparam integer ACTIVE_COUNT_W=$clog2(TILE+1);
 localparam integer POOL_SUM_WIDTH=8+$clog2(POOL_MAX_TAPS);
 localparam integer AVG_SCALE_BITS=8+$clog2(POOL_MAX_TAPS+1);
 wire [ACTIVE_COUNT_W-1:0] active=active_input[ACTIVE_COUNT_W-1:0];
 wire signed [POOL_SUM_WIDTH-1:0] avg_pool_sum=sum_input[POOL_SUM_WIDTH-1:0];
 wire [AVG_SCALE_BITS-1:0] avg_numerator_q=numerator_input[AVG_SCALE_BITS-1:0];
 wire [AVG_SCALE_BITS:0] avg_check_q=check_input[AVG_SCALE_BITS:0];
 {definitions}
'''
    for index, (name, width, expression) in enumerate(values):
        body += f' wire {width} result_{index} = {expression};\n assign value[{64*index}+:64] = 64\'(result_{index});\n'
    return body + 'endmodule\n', len(values)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository',type=Path,default=ROOT)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--reference-rev',default='0097b66ed57e1b8ef00e402e89dc5b274f1626be')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--iverilog',default='iverilog');parser.add_argument('--vvp',default='vvp')
    args=parser.parse_args();repository=args.repository.resolve();root=args.source_root.resolve();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    sys.path.insert(0,str(repository/'test'));from rtl_reference import read_rtl_source
    reference_engine=read_rtl_source(args.reference_rev+':'+ENGINE.as_posix(),cwd=repository,text=True)
    reference_checker=read_rtl_source(args.reference_rev+':'+CHECKER.as_posix(),cwd=repository,text=True)
    sources={ENGINE:(root/ENGINE).read_text(),CHECKER:(root/CHECKER).read_text()}
    hashes={str(path):digest(root/path) for path in sources}
    paths=[];count=0
    for label,engine,checker,candidate in [('reference',reference_engine,reference_checker,False),('candidate',sources[ENGINE],sources[CHECKER],True)]:
        contents,local_count=model(label,engine,checker,candidate);path=out/(label+'.sv');path.write_text(contents);paths.append(path)
        assert count in (0,local_count);count=local_count
    header=(out/'reference.sv').read_text().split(');',1)[0]
    ports=header[header.index('(\n input')+2:].replace(f'output wire [{64*count-1}:0] value', 'output logic equal')
    names=','.join('image_'+field for field in IMAGE_FIELDS)+',config_output_base,channels,range_base_q,range_end_q,output_end_q,channel_base,fetch_ox,ox,oy,active_input,sum_input,numerator_input,check_input'
    binds=','.join('.'+name for name in names.split(','))
    miter=out/'comparison.sv';miter.write_text(f'''module comparison #(parameter integer TILE=16, POOL_MAX_TAPS=256)(
{ports});
 wire [{64*count-1}:0] reference_value,candidate_value;
 native_reference #(.TILE(TILE),.POOL_MAX_TAPS(POOL_MAX_TAPS)) u_reference ({binds},.value(reference_value));
 native_candidate #(.TILE(TILE),.POOL_MAX_TAPS(POOL_MAX_TAPS)) u_candidate ({binds},.value(candidate_value));
 assign equal=reference_value==candidate_value;
endmodule
''')
    packages=[root/'rtl/npu/conv/conv_im2col_pkg.sv',root/'rtl/npu/conv/vector_engine_pkg.sv'];runs=[]
    for tile,pool in PROFILES:
        tag=f't{tile}_p{pool}';script=out/(tag+'.ys');log=out/(tag+'.log')
        script.write_text(f'read_slang --top comparison -GTILE={tile} -GPOOL_MAX_TAPS={pool} '+shlex.join(map(str,packages+paths+[miter]))+'\nprep -top comparison -flatten\nopt_clean\nsat -verify -prove equal 1 -show-inputs -show-outputs\n')
        with log.open('w') as f:result=subprocess.run([sys.executable,repository/'scripts/fpga/open_fpga_synth.py','--worker',script],stdout=f,stderr=subprocess.STDOUT,cwd=repository)
        if result.returncode:raise RuntimeError('算术形式检查未通过：'+tag)
        runs.append({'tile':tile,'pool_max_taps':pool,'passed':True,'log_sha256':digest(log)})
    declarations=ports.replace('input logic','logic').replace(',\n',';\n').replace('output logic equal\n','')
    bench='module tb;\n'+declarations+'\ninteger seed,unused_seed,k,checks;\nlogic [15:0] temporary16;logic [31:0] temporary32;\n'
    for i,(tile,pool) in enumerate(PROFILES):
        bench+=f'wire [{64*count-1}:0] r{i},g{i};\nnative_reference #(.TILE({tile}),.POOL_MAX_TAPS({pool})) r_{i} ({binds},.value(r{i}));\nnative_candidate #(.TILE({tile}),.POOL_MAX_TAPS({pool})) g_{i} ({binds},.value(g{i}));\n'
    bench+='task check; #1;\n'
    for i in range(len(PROFILES)):bench+=f'if(r{i} !== g{i}) $fatal(1,"arithmetic profile={i} sample=%0d reference=%h candidate=%h",k,r{i},g{i}); checks=checks+1;\n'
    bench+='endtask\ninitial begin seed=32\'h29f3417a;unused_seed=$urandom(seed);checks=0;\nfor(k=0;k<32768;k=k+1) begin\n'
    for field in IMAGE_FIELDS:bench+=f'image_{field}=$urandom();\n'
    for name in ['channels','range_base_q','channel_base','fetch_ox','ox','oy','active_input','sum_input','numerator_input','check_input']:bench+=name+'=$urandom();\n'
    bench+='range_end_q={$urandom(),1\'($urandom())};output_end_q={$urandom(),1\'($urandom())};config_output_base=$urandom();\n'
    bench+='''case(k%5)
 1:begin temporary16=image_input_w;temporary16[$urandom()%16]=1'bx;image_input_w=temporary16;temporary16=image_stride_h;temporary16[$urandom()%16]=1'bz;image_stride_h=temporary16;temporary16=image_pad_left;temporary16[$urandom()%16]=1'bx;image_pad_left=temporary16;end
 2:begin sum_input[$urandom()%24]=1'bx;numerator_input[$urandom()%24]=1'bz;check_input[$urandom()%25]=1'bx;end
 3:begin temporary32=config_output_base;temporary32[$urandom()%32]=1'bx;config_output_base=temporary32;range_end_q[$urandom()%33]=1'bz;output_end_q[$urandom()%33]=1'bx;end
 4:begin active_input[$urandom()%7]=1'bx;channel_base[$urandom()%16]=1'bz;fetch_ox[$urandom()%16]=1'bx;ox[$urandom()%16]=1'bz;oy[$urandom()%16]=1'bx;end
endcase
check();
end
$display("VECTOR_NATIVE_ARITHMETIC_PASS profile_checks=%0d",checks);$finish;
end
endmodule
'''
    tb=out/'four_state.sv';tb.write_text(bench);binary=out/'four_state.vvp'
    for name,command in [('build',[args.iverilog,'-g2012','-s','tb','-o',str(binary),*map(str,packages+paths+[tb])]),('four_state',[args.vvp,str(binary)])]:
        p=subprocess.run(command,capture_output=True,text=True,cwd=repository,timeout=180);(out/(name+'.log')).write_text(p.stdout+p.stderr)
        if p.returncode:raise RuntimeError('算术四态检查未通过：'+name)
    matched=re.search(r'profile_checks=(\d+)',(out/'four_state.log').read_text());assert matched
    assert hashes=={str(path):digest(root/path) for path in sources}
    report={'passed':True,'reference_revision':args.reference_rev,'source_sha256':hashes,'operation_count':count,'formal':runs,'strict_four_state_profile_checks':int(matched[1]),'strict_four_state_arithmetic_results':int(matched[1])*count,'test_sha256':digest(Path(__file__).resolve()),'four_state_log_sha256':digest(out/'four_state.log')}
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
