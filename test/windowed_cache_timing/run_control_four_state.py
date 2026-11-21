#!/usr/bin/env python3
"""检查缓存填充资格与完整区间减法的四态结果。"""
import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def qualification_test(source, set_width, helpers):
    fields = [('select_stage_valid', 1), ('select_decision_valid', 1), ('req_fire', 1),
              ('lookup_set', set_width), ('select_set', set_width), ('hint_pending_q', 1),
              ('hint_effective_valid', 1), ('hint_set', set_width), ('fill_state', 2),
              ('fill_set', set_width), ('span_rsp_valid', 1), ('span_rsp_ready', 1),
              ('span_last', 1), ('fill_bad', 1), ('span_error', 1)]
    width = sum(bits for _, bits in fields)
    decl = '\n'.join(f'logic [{bits-1}:0] {name};' for name, bits in fields)
    drive = '{' + ','.join(name for name, _ in fields) + '}'
    begin = source.index('  logic select_nonfill_busy;')
    end = source.index('  assign select_prefetch_ready', begin)
    actual = source[begin:end]
    definition = '\n'.join(helpers.assignment(source, name) for name in
                           ('fill_complete', 'fill_success', 'select_metadata_busy'))
    return f'''module tb;
 localparam integer WIDTH={width};
 localparam logic [1:0] F_IDLE=0,F_DATA=2;
 logic [WIDTH-1:0] stimulus,saved;
 {decl}
 logic fill_complete,fill_success,select_metadata_busy,select_common_ready;
 wire metadata_fill=fill_complete;
 integer checks=0,seed=32'h1a2785f0;
 assign {drive}=stimulus;
 {definition}
 {actual}
 wire expected=select_stage_valid&&select_decision_valid&&!select_metadata_busy&&(fill_state==F_IDLE||fill_success);
 task automatic check;
 #1;
 if(select_common_ready !== expected) $fatal(1,"fill qualification stimulus=%b actual=%b expected=%b",stimulus,select_common_ready,expected);
 checks++;
 endtask
 initial begin
 for(integer trial=0;trial<4096;trial++) begin
 for(integer b=0;b<WIDTH;b++) stimulus[b]=$random(seed);
 check();saved=stimulus;
 for(integer b=0;b<WIDTH;b++) begin
 stimulus=saved;stimulus[b]=1'bx;check();stimulus=saved;stimulus[b]=1'bz;check();
 end
 end
 stimulus='x;check();stimulus='z;check();
 $display("FOUR_STATE_PASS checks=%0d",checks);$finish;
 end
 endmodule
'''


def length_test(source, helpers):
    assignment = helpers.assignment(source, "span_request_bytes_wide")
    return f'''module tb;
 logic [31:0] fill_end,fill_first;
 logic [32:0] span_request_bytes_wide;
 logic [63:0] stimulus,saved;
 integer checks=0,seed=32'h1086f5a2;
 assign {{fill_end,fill_first}}=stimulus;
 {assignment}
 wire [15:0] expected=16'(fill_end-fill_first);
 task automatic check;
 #1;if(span_request_bytes_wide[15:0] !== expected) $fatal(1,"span difference stimulus=%b actual=%b expected=%b",stimulus,span_request_bytes_wide[15:0],expected);checks++;
 endtask
 initial begin
 for(integer trial=0;trial<4096;trial++) begin
 stimulus={{$random(seed),$random(seed)}};check();saved=stimulus;
 for(integer b=0;b<64;b++) begin
 stimulus=saved;stimulus[b]=1'bx;check();stimulus=saved;stimulus[b]=1'bz;check();
 end
 end
 stimulus='x;check();stimulus='z;check();
 $display("FOUR_STATE_PASS checks=%0d",checks);$finish;
 end
 endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, default=ROOT/'build/windowed_cache_timing/four_state_arithmetic')
    args = parser.parse_args()
    helper_path = HERE/'run_four_state.py'
    spec = importlib.util.spec_from_file_location('cache_four_state', helper_path)
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    rtl = args.source_root.resolve()/'rtl/npu/dma/cache/conv_read_cache.sv'
    source = rtl.read_text()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    hashes = {str(path): helpers.digest(path) for path in (rtl, helper_path, Path(__file__))}
    records = []
    for set_width in (1, 4):
        record = helpers.run_test(out, f'qualification_{1<<set_width}',
                                  qualification_test(source, set_width, helpers))
        records.append(record)
        print(json.dumps(record), flush=True)
    record = helpers.run_test(out, 'span_length', length_test(source, helpers))
    records.append(record)
    print(json.dumps(record), flush=True)
    if hashes != {name: helpers.digest(Path(name)) for name in hashes}:
        raise RuntimeError('验证期间源文件发生变化')
    report = {'passed': True, 'source_sha256': hashes, 'profiles': records,
              'checks': sum(row['checks'] for row in records)}
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
