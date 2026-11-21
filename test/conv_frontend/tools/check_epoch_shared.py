#!/usr/bin/env python3
"""证明连续请求的通道纪元共用算术结果。"""
import argparse
from pathlib import Path
import shlex
import hashlib
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out, source_root = args.out.resolve(), args.source_root.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current_path = source_root / 'rtl/npu/conv/conv_im2col_frontend.sv'
    reference_path = args.reference_root.resolve() / 'rtl/npu/conv/conv_im2col_frontend.sv'
    old, new = reference_path.read_text(), current_path.read_text()
    current_sha = hashlib.sha256(current_path.read_bytes()).hexdigest()
    reference_sha = hashlib.sha256(reference_path.read_bytes()).hexdigest()
    select = new[new.index("  assign chunk_selected[0]"):new.index('  logic incoming_request')]
    old_start = old.index('      logic [LANES:0][17:0] step_sum;')
    old_stop = old.index('    end else begin : g_general', old_start)
    old_math = old[old_start:old_stop].replace('epoch_o_sum[candidate]', 'reference_sum')
    old_math = re.sub(r'      assign unused_epoch_carry\[candidate\] = 1\'b0;\n', '', old_math)
    new_start = new.index('      (* use_dsp = "yes" *) logic [17:0] channel_sum;')
    new_stop = new.index('    end else begin : g_general', new_start)
    new_math = new[new_start:new_stop].replace('epoch_i_a[candidate][17:0]', 'sum_xor')
    new_math = new_math.replace('epoch_i_b[candidate][17:0]', 'sum_carry')
    new_math = new_math.replace('epoch_o_sum[candidate]', 'current_sum')
    new_math = re.sub(r'      assign unused_epoch_carry\[candidate\] = 1\'b0;\n', '', new_math)
    runs = []
    for lanes in (1,2,3,4,5,6,7,8):
        for contiguous in (False,True):
            name=f'l{lanes}_contiguous{int(contiguous)}'
            header=f'''module proof(input logic[15:0]group_offset,ch_q,
 input logic[{lanes-1}:0]mask, output logic equivalent);
 localparam int LANES={lanes},CHUNK_COUNT_W=$clog2(LANES+1);
 localparam bit p_contiguous_chunk=1'b{int(contiguous)};
 typedef struct packed {{logic[15:0]group_offset;}} cfg_t;
 cfg_t c;
 assign c.group_offset=group_offset;
 logic[LANES-1:0]chunk_lane_allowed;
 logic[LANES:0]chunk_selected;
 logic[CHUNK_COUNT_W-1:0]chunk_count;
 logic[17:0]sum_xor,sum_carry;
 logic[31:0]reference_sum,current_sum;
 assign chunk_lane_allowed=mask;
 always_comb begin
   chunk_count='0;
   for(int lane=0;lane<LANES;lane++)
     if(chunk_lane_allowed[lane])chunk_count=CHUNK_COUNT_W'(lane+1);
 end
 assign sum_xor={{2'b0,group_offset}}^{{2'b0,ch_q}}^18'(chunk_count);
 assign sum_carry=(({{2'b0,group_offset}}&{{2'b0,ch_q}})|
     (({{2'b0,group_offset}}|{{2'b0,ch_q}})&18'(chunk_count)))<<1;
'''
            prop = "assign equivalent="
            if contiguous:
                prop += "((mask & (mask + LANES'(1))) != '0) || "
            prop += '(reference_sum==current_sum);\nendmodule\n'
            source = header+select+old_math+new_math+prop
            sv,ys,log=[out/(name+suffix)for suffix in ('.sv','.ys','.log')]
            sv.write_text(source)
            ys.write_text('read_slang --top proof ' + shlex.join([str(sv), str(source_root / 'rtl/common/parallel_prefix_add.sv')]) + '\n'
                          'prep -top proof -flatten\nopt\ncheck -assert\n'
                          'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
            with log.open('w')as stream:
                result=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                                       '--worker',str(ys)],stdout=stream,stderr=subprocess.STDOUT,timeout=60)
            if result.returncode or 'SAT proof finished - no model found: SUCCESS!'not in log.read_text():
                raise RuntimeError(str(log))
            runs.append(dict(name=name,passed=True,lanes=lanes,
                             contiguous_mask_required=contiguous,
                             source_sha256=hashlib.sha256(sv.read_bytes()).hexdigest()))
    if current_sha != hashlib.sha256(current_path.read_bytes()).hexdigest() or reference_sha != hashlib.sha256(reference_path.read_bytes()).hexdigest():
        raise RuntimeError('Source changed during verification')
    report=dict(passed=True,runs=runs,
                source_sha256=current_sha,
                reference_sha256=reference_sha,
                result_bits=32,arithmetic_inputs_unconstrained=True)
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print('EPOCH_SHARED_PASS',len(runs),out/'summary.json')


if __name__=='__main__':
    main()
