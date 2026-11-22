#!/usr/bin/env python3
"""比较完整元数据银行的四态读取、同址转发和状态保持。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[2]
CACHE = Path('rtl/npu/dma/cache/conv_windowed_cache.sv')
CHILD = Path('rtl/npu/dma/cache/conv_cache_metadata_way.sv')
PROFILES = ((2, 1, 4, 1), (8, 2, 4, 1), (8, 1, 4, 4), (16, 2, 7, 2))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metadata_region(text: str) -> str:
    match = re.search(r'  for\s*\(genvar metadata_way\s*=\s*0;', text)
    if match is None:
        raise ValueError('元数据银行实例缺失')
    end = text.index('\n  end\n', match.start()) + len('\n  end\n')
    return text[match.start():end]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    roots = {'reference': args.reference_root.resolve(), 'current': args.source_root.resolve()}
    bodies = {label: metadata_region((root / CACHE).read_text()) for label, root in roots.items()}
    dependencies = []
    for name in ('rtl/common/regfile.v', 'rtl/npu/dma/cache/conv_cache_rank_table.sv'):
        if (roots['reference'] / name).read_bytes() != (roots['current'] / name).read_bytes():
            raise ValueError(f'两侧必须使用相同存储实现：{name}')
        dependencies.append(roots['current'] / name)
    dependencies.append(roots['current'] / CHILD)
    report = {'passed': False, 'strict_four_state_equivalence': True, 'profiles': [],
              'source_sha256': {label: digest(root / CACHE) for label, root in roots.items()},
              'metadata_sha256': digest(roots['current'] / CHILD)}
    for sets, ways, line_shift, demand_depth in PROFILES:
        si, wi = (sets - 1).bit_length(), max(1, (ways - 1).bit_length())
        dq_aw, dq_cw = max(1, (demand_depth - 1).bit_length()), demand_depth.bit_length()
        epoch_width, tag_width = 17 - line_shift, 32 - line_shift
        folder = out / f's{sets}_w{ways}_l{line_shift}_d{demand_depth}'
        folder.mkdir(exist_ok=True)
        fields = [(name, 1, '') for name in (
            'rst_n', 'cfg_valid', 'cfg_ready', 'configured', 'clearing', 'bypass_q', 'windowed_q',
            'metadata_enable', 'metadata_fill', 'metadata_fill_good', 'metadata_hit',
            'offer_capture', 'req_fire', 'req_valid', 'saved_fill_match',
            'hint_resolved', 'hint_valid', 'select_stage_valid')]
        fields += [('fill_state', 2, ''), ('fg_state', 2, ''), ('fill_way', wi, ''),
                   ('lookup_way', wi, ''), ('request_count', dq_cw, ''), ('request_head', dq_aw, '')]
        fields += [(name, si, '') for name in (
            'clear_set', 'fill_set', 'lookup_set', 'candidate_set', 'lookup_read_set',
            'lookup_snapshot_set', 'pf_set', 'offer_set_q', 'offer_next_set_q', 'select_set',
            'hint_set', 'initial_pf_set', 'next_pf_set')]
        fields += [('lookup_candidate_set', 4 * si, f'[3:0][{si-1}:0]'),
                   ('lookup_candidate_select', 2, ''), ('hint_tag', tag_width, f'[31:{line_shift}]')]
        fields += [(name, 32, '') for name in (
            'fill_addr', 'fill_epoch', 'work_epoch', 'hint_effective_value',
            'metadata_fill_rank', 'metadata_hit_rank')]
        input_bits = sum(width for _, width, _ in fields)
        per_way = 6 + 5 * tag_width + epoch_width + 32 + (tag_width if demand_depth == 1 else 0)
        output_bits = per_way * ways
        offsets, offset = {}, 0
        declarations = []
        for name, width, kind in fields:
            kind = kind or f'[{width-1}:0]'
            declarations.append(f'  wire {kind} {name};\n  assign {name}=stimulus[{offset}+:{width}];')
            offsets[name] = (offset, width)
            offset += width
        common = '\n'.join(declarations) + f'''
  localparam SETS={sets}, WAYS={ways}, SI={si}, WI={wi}, LB={line_shift};
  localparam EPOCH_W={epoch_width}, DEMAND_DEPTH={demand_depth};
  localparam [1:0] F_IDLE=2'd0;
  typedef struct packed {{logic [31:0] epoch;}} request_t;
  wire request_t work_request;
  assign work_request.epoch=work_epoch;
  wire [WAYS-1:0] valid_lookup,valid_prefetch,valid_incoming,valid_next,valid_select,valid_hint;
  wire [WAYS-1:0][31:LB] lookup_tag,pf_tag,incoming_tag,next_tag,hint_lookup_tag;
  wire [EPOCH_W-1:0] select_epochs[WAYS];
  wire [31:0] select_ranks[WAYS];
  if(1) begin:g_saved_fill_match
    wire lookup_fill_set_match_q=saved_fill_match;
  end
  if(1) begin:g_direct_tag_compare
    wire [WAYS-1:0][31:LB] lookup_tag_raw;
  end
'''
        results = []
        for way in range(ways):
            values = [f'{name}[{way}]' for name in ('valid_hint', 'valid_select', 'valid_next',
                'valid_incoming', 'valid_prefetch', 'valid_lookup', 'lookup_tag', 'pf_tag',
                'incoming_tag', 'next_tag', 'hint_lookup_tag', 'select_epochs', 'select_ranks')]
            if demand_depth == 1:
                values.append(f'g_direct_tag_compare.lookup_tag_raw[{way}]')
            results.append(f'  assign result[{way*per_way}+:{per_way}]={{' + ','.join(values) + '};')
        models = []
        for label, body in bodies.items():
            model = folder / (label + '.sv')
            model.write_text(f'module metadata_{label}(input wire clk,\n' +
                f'  input wire [{input_bits-1}:0] stimulus,output wire [{output_bits-1}:0] result);\n' +
                common + body + '\n'.join(results) + '\nendmodule\n')
            models.append(model)
        assignments = '\n'.join(f'`define SET_{name}(value) stimulus[{first}+:{width}]=value'
                                 for name, (first, width) in offsets.items())
        bench = folder / 'tb.sv'
        bench.write_text(assignments + f'''
module tb;
  localparam BITS={input_bits}, RESULTS={output_bits}, SETS={sets}, WAYS={ways};
  reg clk=0;
  reg [BITS-1:0] stimulus='0;
  wire [RESULTS-1:0] a,b;
  integer checks=0,known_bits=0,unknown_bits=0;
  reg [31:0] random_state=32'h75ab91e3;
  metadata_reference reference_dut(.clk(clk),.stimulus(stimulus),.result(a));
  metadata_current current_dut(.clk(clk),.stimulus(stimulus),.result(b));
  function automatic [31:0] step(input [31:0] value);
    reg [31:0] next_value;
    begin
      next_value=value^(value<<13);next_value=next_value^(next_value>>17);
      step=next_value^(next_value<<5);
    end
  endfunction
  task check;
    begin
      #1;
      if(a!==b) $fatal(1,"Metadata mismatch check=%0d inputs=%h old=%h current=%h",checks,stimulus,a,b);
      checks++;
      for(integer bit_index=0;bit_index<RESULTS;bit_index++)
        if(a[bit_index]===1'b0 || a[bit_index]===1'b1)known_bits++;
        else unknown_bits++;
    end
  endtask
  task cycle;
    begin check();clk=1;check();clk=0;end
  endtask
  initial begin
    cycle();
    `SET_rst_n(1);`SET_configured(1);`SET_metadata_enable(1);`SET_clearing(1);
    for(integer address=0;address<SETS;address++)begin
      `SET_clear_set(address);cycle();
    end
    `SET_clearing(0);`SET_metadata_fill(1);`SET_metadata_fill_good(1);
    for(integer way=0;way<WAYS;way++)begin
      `SET_fill_way(way);
      for(integer address=0;address<SETS;address++)begin
        `SET_fill_set(address);`SET_lookup_read_set(address);`SET_lookup_snapshot_set(address);
        `SET_pf_set(address);`SET_offer_set_q(address);`SET_offer_next_set_q(address);
        `SET_select_set(address);`SET_hint_set(address);`SET_candidate_set(address);
        `SET_fill_addr(32'hc000+32'(address*{1<<line_shift}));
        `SET_fill_epoch(37+way);`SET_metadata_fill_rank(32'h1000+32'(address));cycle();
      end
    end
    for(integer sample=0;sample<6000;sample++)begin
      for(integer bit_index=0;bit_index<BITS;bit_index++)begin
        random_state=step(random_state);stimulus[bit_index]=random_state[0];
        if(sample>=500 && sample%13==0)begin
          if(random_state[3:0]==0)stimulus[bit_index]=1'bx;
          if(random_state[3:0]==1)stimulus[bit_index]=1'bz;
        end
      end
      if(sample>=500 && sample%13!=0)begin
        if(sample%2)stimulus[sample%BITS]=1'bx;
        else stimulus[sample%BITS]=1'bz;
      end
      cycle();
    end
    $display("METADATA_FOUR_STATE_PASS checks=%0d known_bits=%0d unknown_bits=%0d",checks,known_bits,unknown_bits);
    $finish;
  end
endmodule
''')
        binary = folder / 'run.vvp'
        with (folder / 'compile.log').open('w') as stream:
            subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', str(binary),
                            *map(str, dependencies + models + [bench])], cwd=ROOT,
                           stdout=stream, stderr=subprocess.STDOUT, check=True)
        with (folder / 'run.log').open('w') as stream:
            subprocess.run(['vvp', str(binary)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True, timeout=180)
        text = (folder / 'run.log').read_text()
        matched = re.search(r'METADATA_FOUR_STATE_PASS checks=(\d+) known_bits=(\d+) unknown_bits=(\d+)', text)
        if matched is None:
            raise RuntimeError('元数据四态检查结果缺失')
        row = {'sets': sets, 'ways': ways, 'line_bytes': 1 << line_shift, 'demand_depth': demand_depth,
               'input_bits': input_bits, 'output_bits': output_bits, 'passed': True,
               **dict(zip(['checks', 'known_bits', 'unknown_bits'], map(int, matched.groups()))),
               'log_sha256': digest(folder / 'run.log')}
        report['profiles'].append(row)
        print(json.dumps(row), flush=True)
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
