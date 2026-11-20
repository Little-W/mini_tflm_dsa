#!/usr/bin/env python3
"""证明向量 DMA 地址共享保持全部组合输出和参数检查结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT=Path(__file__).resolve().parents[2]
SOURCE='rtl/npu/conv/vector_engine.sv'


def span(source):
    first=source.index('  assign rd_start =')
    first=source.index('\n',first)+1
    return first,source.index('  wire signed [15:0] input_lane',first)


def remainder(source):
    first,last=span(source)
    marker='  logic [32:0] dma_range_size' if '  logic [32:0] dma_range_size' in source else '  // Parameter and cached-input phases configure'
    config_first=source.index(marker)
    config_last=source.index('  assign rd_req',config_first)
    unchanged=source[:config_first]+source[config_last:first]+source[last:]
    unchanged=re.sub(r'^module vector_read_address_add\b.*?^endmodule','',unchanged,flags=re.M|re.S)
    return re.sub(r'\s+','',re.sub(r'/\*.*?\*/|//[^\n]*','',unchanged,flags=re.S))


def fragment(source,bus,tile):
    first,last=span(source)
    state=re.search(r'typedef enum logic \[5:0\].*?state_t;',source,re.S)[0]
    load=re.search(r'typedef enum logic \[2:0\].*?load_t;',source,re.S)[0]
    helper=re.search(r'^module vector_read_address_add\b.*?^endmodule',source,re.M|re.S)
    return f'''module vector_read_decode #(
      parameter int BUS_WIDTH={bus}, TILE={tile}, DMA_SIZE=4*TILE,
      parameter int BUS_BYTES=BUS_WIDTH/8, BUS_SHIFT=$clog2(BUS_BYTES),
      parameter int INPUT_INDEX_W=$clog2(DMA_SIZE), ACTIVE_COUNT_W=$clog2(TILE+1)
    ) (
      input logic clk,
      input logic [5:0] state,
      input logic [2:0] load_kind,
      input vector_engine_pkg::vector_engine_cfg_t c,
      input logic spatial, rd_raw_valid,
      input logic [ACTIVE_COUNT_W-1:0] active,
      input logic [15:0] channel_base,
      input logic [31:0] vector_offset,load_tap_offset,pool_byte_offset,channels,
      input logic [7:0] soft_lut_index,
      input logic [INPUT_INDEX_W:0] pool_elements,pool_pixels,
      input logic [INPUT_INDEX_W-1:0] rd_col_base,
      input logic [BUS_WIDTH-1:0] rd_raw_data,
      output logic rd_im2col,rd_use_16bits,param_bad,
      output logic [31:0] rd_p0,rd_q0,rd_base_addr,rd_row_stride,rd_rows_to_read,rd_valid_cols,load_bytes,
      output logic [7:0] rd_burst_len_m1
    );
      {state}
      {load}
      {source[first:last]}
    endmodule
    {helper.group() if helper else ''}
    '''


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--reference-rev',default='2f06471c');args=p.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    ref=read_rtl_source(args.reference_rev+':'+SOURCE, cwd=ROOT, text=True)
    cand=(ROOT/SOURCE).read_text()
    packages=[ROOT/'rtl/npu/conv/conv_im2col_pkg.sv',ROOT/'rtl/npu/conv/vector_engine_pkg.sv']
    report={'reference_rev':args.reference_rev,'source_sha256':hashlib.sha256(cand.encode()).hexdigest(),
            'reference_sha256':hashlib.sha256(ref.encode()).hexdigest(),'inputs_constrained':False,
            'source_unchanged_outside_dma_config_and_read_decode':remainder(ref)==remainder(cand),
            'proof_scope':'Complete DMA configuration and read decode outputs extracted from vector_engine RTL','runs':[]}
    cases={}
    for bus,tile in [(32,16),(64,16),(128,16),(32,3),(64,32)]:
        folder=out/f'bus{bus}_tile{tile}';folder.mkdir(exist_ok=True);commands=[]
        for label,source in [('reference',ref),('candidate',cand)]:
            path=folder/(label+'.sv');path.write_text(fragment(source,bus,tile))
            commands+=['read_slang -D ASIC_SYNTHESIS=1 --top vector_read_decode '+' '.join(shlex.quote(str(p)) for p in packages+[path]),
                       'prep -top vector_read_decode -flatten','opt -full','rename vector_read_decode '+label,'design -stash '+label]
            if (bus,tile)==(64,16):
                cases[label]={'top':'vector_read_decode','options':[],'sources':[str(p) for p in packages+[path]],
                              'configuration':'BUS64 TILE16; all states and read request outputs'}
        commands+=['design -copy-from reference -as reference reference','design -copy-from candidate -as candidate candidate',
                   'equiv_make reference candidate comparison','hierarchy -top comparison','equiv_simple','equiv_status -assert']
        script=folder/'run.ys';script.write_text('\n'.join(commands)+'\n');log=folder/'formal.log'
        with log.open('w') as stream:
            r=subprocess.run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
        text=log.read_text();match=re.search(r'Of those cells (\d+) are proven and (\d+) are unproven',text)
        row={'bus_width':bus,'tile':tile,'equivalent_bits':int(match[1]) if match else None,
             'passed':r.returncode==0 and 'Equivalence successfully proven' in text,
             'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()}
        report['runs'].append(row);print(json.dumps(row),flush=True)
        if not row['passed']:raise RuntimeError(text[-8000:])
    range_out=out/'ranges'
    subprocess.run([sys.executable,Path(__file__).with_name('run_ranges_formal.py'),
                    '--out',range_out,'--reference-rev',args.reference_rev],cwd=ROOT,check=True)
    report['ranges']=json.loads((range_out/'summary.json').read_text())
    assert (ROOT/SOURCE).read_text()==cand
    report['passed']=True
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    (out/'cases.json').write_text(json.dumps(cases,indent=2)+'\n')


if __name__=='__main__':
    main()
