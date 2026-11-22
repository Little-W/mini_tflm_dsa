#!/usr/bin/env python3
"""验证通用参数下输入数据、池化响应和逐项存储的完整状态更新。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from open_fpga_synth import process_tree_rss
SOURCE = Path('rtl/npu/conv/vector_engine.sv')


def extract(text):
    start = text.index('  wire [BUS_SHIFT-1:0] pool_first_bank=')
    end = text.index('  // 空间响应保存原始数据', start)
    parts = [text[start:end]]
    start = text.index('  for (genvar bank=0;bank<INPUT_BANKS;bank++) begin : g_input_bank_data')
    end = text.index('  // 一个银行每拍至多写入一行', start)
    parts.append(text[start:end])
    start = text.index('  for (genvar entry=0;entry<DMA_SIZE;entry++) begin : g_input_write')
    end = text.index('  // 每拍的连续偏置字', start)
    parts.append(text[start:end])
    return '\n'.join(parts)


def model(name, body, tile, bus, windows):
    lanes = bus // 8
    correspondence = ''
    if 'logic signed [15:0] data;' in body:
        correspondence = """
  for(genvar lane=0;lane<BUS_BYTES;lane++)begin : g_data_correspondence
    assign pool_bank_data[lane]=g_pool_bank[lane].g_rotated_register.data;
  end
"""
    return f'''module {name} (
  input logic clk,rst_n,global_pool,spatial,vector_s16,pool_response_fire,
  input logic [6:0] pool_received,pool_elements,
  input logic [4:0] pool_beat_count,
  input logic [{16*lanes-1}:0] raw_dma_data,
  input logic [{16*windows-1}:0] raw_window_data,
  input logic [{lanes-1}:0] raw_dma_valid,
  input logic [{6*lanes-1}:0] raw_dma_index,
  input logic [{windows-1}:0] window_bank_valid,
  input logic [{6*windows-1}:0] raw_window_index,
  output logic [{16*4*tile-1}:0] stored,
  output logic [{lanes-1}:0] pool_bank_valid,
  output logic [{4*lanes-1}:0] pool_rows,
  output logic [{16*lanes-1}:0] pool_words
);
  localparam int TILE={tile},BUS_WIDTH={bus},WINDOW_LANES={windows};
  localparam int DMA_SIZE=4*TILE,INPUT_STORED_ELEMENTS=2*TILE;
  localparam int INPUT_INDEX_W=$clog2(DMA_SIZE),BUS_BYTES=BUS_WIDTH/8,BUS_SHIFT=$clog2(BUS_BYTES);
  localparam int INPUT_BANKS=WINDOW_LANES>BUS_BYTES ? WINDOW_LANES : BUS_BYTES;
  localparam int POOL_ROW_W=INPUT_INDEX_W>BUS_SHIFT ? INPUT_INDEX_W-BUS_SHIFT : 1;
  localparam bit p_input_bank_storage=1'b0;
  typedef struct packed {{logic vector_s16;}} cfg_t;
  cfg_t c;
  assign c.vector_s16=vector_s16;
  wire signed [15:0] rd_data[BUS_BYTES],window_bank_data[WINDOW_LANES];
  wire dma_input_write_valid[BUS_BYTES];
  wire [INPUT_INDEX_W-1:0] dma_input_write_index[BUS_BYTES],window_bank_index[WINDOW_LANES];
  logic [POOL_ROW_W-1:0] pool_bank_row[BUS_BYTES];
  wire signed [15:0] input_bank_data[INPUT_BANKS];
  logic signed [15:0] pool_bank_data[BUS_BYTES],input_buf[DMA_SIZE];
  for(genvar lane=0;lane<BUS_BYTES;lane++)begin : g_dma_port
    assign rd_data[lane]=raw_dma_data[16*lane+:16];
    assign dma_input_write_valid[lane]=raw_dma_valid[lane];
    assign dma_input_write_index[lane]=INPUT_INDEX_W'(raw_dma_index[6*lane+:6]);
    assign pool_rows[4*lane+:4]=4'(pool_bank_row[lane]);
    assign pool_words[16*lane+:16]=pool_bank_data[lane];
  end
  for(genvar lane=0;lane<WINDOW_LANES;lane++)begin : g_window_port
    assign window_bank_data[lane]=raw_window_data[16*lane+:16];
    assign window_bank_index[lane]=INPUT_INDEX_W'(raw_window_index[6*lane+:6]);
  end
  for(genvar entry=0;entry<DMA_SIZE;entry++)begin : g_output
    assign stored[16*entry+:16]=input_buf[entry];
  end
{body}
{correspondence}
endmodule
'''


def execute(script, log):
    start = time.monotonic()
    peak = 0
    with log.open('w') as stream:
        proc = subprocess.Popen([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                                 '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT)
        while proc.poll() is None:
            memory = process_tree_rss(proc.pid)
            peak = max(memory, peak)
            if memory > 384*1024*1024 or time.monotonic()-start > 180:
                proc.terminate()
                proc.wait(timeout=10)
                raise RuntimeError('分组证明超出已设置的资源限制')
            time.sleep(0.1)
        if proc.returncode:
            raise RuntimeError(log.read_text()[-3000:])
    return {'elapsed_seconds': round(time.monotonic()-start, 2),
            'peak_process_tree_rss_bytes': peak}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root', type=Path, default=ROOT)
    p.add_argument('--reference-root', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    roots={'reference':a.reference_root.resolve(),'current':a.source_root.resolve()}
    hashes={label:hashlib.sha256((root/SOURCE).read_bytes()).hexdigest() for label,root in roots.items()}
    runs=[]
    for tile,bus,windows in [(4,32,4),(16,32,4),(16,64,4),(16,32,8)]:
        folder=out/f't{tile}_b{bus}_w{windows}';folder.mkdir(exist_ok=True)
        commands=[]
        for label,root in roots.items():
            target=folder/(label+'.sv');target.write_text(model(label,extract((root/SOURCE).read_text()),tile,bus,windows))
            commands += [f'read_slang --top {label} {target}',f'prep -top {label} -flatten',
                         'memory_map','async2sync','opt_clean',f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference','design -copy-from current -as current current',
                     'miter -equiv -make_assert -flatten reference current miter','hierarchy -top miter',
                     'opt_clean','sat -verify -tempinduct -seq 1 -maxsteps 3 -set-init-zero -prove-asserts']
        script=folder/'run.ys';script.write_text('\n'.join(commands)+'\n');log=folder/'formal.log'
        stage=execute(script,log);text=log.read_text()
        if 'Induction step proven: SUCCESS!' not in text:raise RuntimeError('分组归纳证明尚未完成')
        record={'tile':tile,'bus_width':bus,'window_lanes':windows,'passed':True,
                'complete_storage_state_compared':True,'stage':stage,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()}
        runs.append(record);print(json.dumps(record),flush=True)
    assert hashes=={label:hashlib.sha256((root/SOURCE).read_bytes()).hexdigest() for label,root in roots.items()}
    (out/'summary.json').write_text(json.dumps({'passed':True,'inputs_constrained':False,
        'scope':'实际 RTL 的通用输入保存分支、池化响应数据及全部存储项',
        'initial_state':'两份模型使用相同初始数据，归纳步骤比较完整存储状态的更新',
        'source_sha256':hashes,'runs':runs},ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':main()
