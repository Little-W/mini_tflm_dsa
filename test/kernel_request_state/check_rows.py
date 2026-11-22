"""证明实际权重行组装表达式，并检查四态选择结果。"""
from pathlib import Path
import argparse, json, hashlib, subprocess, sys
ROOT = Path(__file__).resolve().parents[2]
p = argparse.ArgumentParser()
p.add_argument('--source-root', type=Path, default=ROOT)
p.add_argument('--reference-root', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
args = p.parse_args()
OUT = args.out
OUT.mkdir(parents=True, exist_ok=True)
FOLDERS = {'reference': args.reference_root, 'current': args.source_root}
RTL = Path('rtl/npu/loaders/kernel_loader.sv')

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def model(label, path):
    text = path.read_text()
    start = text.index('  // 有效传输的最后一个元素决定整行完成')
    end = text.index('\n\t  always_ff @(posedge clk or negedge rst_n) begin', start)
    return f'module {label} #(parameter integer SIZE=16,DATA_WIDTH=16,BUS_WIDTH=64,REG_WIDTH=32)(\n input logic cache_flush,managed_mode,transfer_discard,response_accept,ext_dma_wr_slot,\n input logic [$clog2(SIZE)-1:0] ext_dma_wr_col_base,\n input logic signed [DATA_WIDTH-1:0] ext_dma_wr_data[(BUS_WIDTH/8<2)?2:BUS_WIDTH/8],\n input logic ext_dma_wr_valid[(BUS_WIDTH/8<2)?2:BUS_WIDTH/8],\n input logic signed [DATA_WIDTH-1:0] row_acc[SIZE],\n input logic [REG_WIDTH-1:0] ext_dma_valid_cols_r[2],\n input logic [REG_WIDTH-1:0] ext_dma_logical_cols_r[2],\n output wire [SIZE*DATA_WIDTH*2+1:0] result);\n localparam integer DMA_LANES=BUS_WIDTH/8;\n logic signed [DATA_WIDTH-1:0] row_acc_n[SIZE],row_emit_n[SIZE];\n logic beat_valid,last_ext_beat;\n {text[start:end]}\n for(genvar i=0;i<SIZE;i++)begin\n  assign result[i*DATA_WIDTH+:DATA_WIDTH]=row_acc_n[i];\n  assign result[(SIZE+i)*DATA_WIDTH+:DATA_WIDTH]=row_emit_n[i];\n end\n assign result[SIZE*DATA_WIDTH*2+:2]={{last_ext_beat,beat_valid}};\n endmodule\n'
models = model('reference', FOLDERS['reference'] / RTL) + model('current', FOLDERS['current'] / RTL)
rows = []
for size, dw, bus in [(4, 8, 8), (4, 8, 24), (4, 8, 32), (6, 16, 64), (16, 16, 32), (16, 16, 64), (16, 16, 128)]:
    folder = OUT / f'{size}_{dw}_{bus}'
    folder.mkdir(exist_ok=True)
    header = f'module top(input wire cache_flush,managed_mode,transfer_discard,response_accept,ext_dma_wr_slot,\n input wire [$clog2({size})-1:0] ext_dma_wr_col_base,\n input wire signed [{dw}-1:0] ext_dma_wr_data[{max(2, bus // 8)}],\n input wire ext_dma_wr_valid[{max(2, bus // 8)}],\n input wire signed [{dw}-1:0] row_acc[{size}],\n input wire [31:0] ext_dma_valid_cols_r[2],ext_dma_logical_cols_r[2],output wire equivalent);\n wire[{size}*{dw}*2+1:0]a,b;\n reference #(.SIZE({size}),.DATA_WIDTH({dw}),.BUS_WIDTH({bus}))r(.*,.result(a));\n current #(.SIZE({size}),.DATA_WIDTH({dw}),.BUS_WIDTH({bus}))c(.*,.result(b));\n assign equivalent=a==b;endmodule\n'
    formal = folder / 'formal.sv'
    formal.write_text(models + header)
    ys = folder / 'prove.ys'
    ys.write_text(f'read_slang --top top {formal}\nprep -top top -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
    with (folder / 'formal.log').open('w') as f:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'), '--worker', str(ys)], stdout=f, stderr=subprocess.STDOUT, check=True, timeout=40)
    bench = folder / 'tb.sv'
    bench.write_text(models.replace('automatic int col;', 'integer col;') + f"""module tb;\n localparam integer SIZE={size},DATA_WIDTH={dw},BUS_WIDTH={bus},LANES=BUS_WIDTH/8;\n logic cache_flush,managed_mode,transfer_discard,response_accept,ext_dma_wr_slot;\n logic[$clog2(SIZE)-1:0]ext_dma_wr_col_base;\n logic signed[DATA_WIDTH-1:0]ext_dma_wr_data[(LANES<2)?2:LANES],row_acc[SIZE];\n logic ext_dma_wr_valid[(LANES<2)?2:LANES];logic[31:0]ext_dma_valid_cols_r[2],ext_dma_logical_cols_r[2];\n wire[SIZE*DATA_WIDTH*2+1:0]a,b;integer checks=0;\n reference #(.SIZE(SIZE),.DATA_WIDTH(DATA_WIDTH),.BUS_WIDTH(BUS_WIDTH))r(.*,.result(a));\n current #(.SIZE(SIZE),.DATA_WIDTH(DATA_WIDTH),.BUS_WIDTH(BUS_WIDTH))c(.*,.result(b));\n function automatic logic f(input integer n);case(n%4)0:return 1'b0;1:return 1'b1;2:return 1'bx;default:return 1'bz;endcase endfunction\n task check;#1;if(a!==b)$fatal(1,"行组装结果不同 sample=%0d col=%b valid=%b ref=%h cur=%h",checks,ext_dma_wr_col_base,response_accept,a,b);checks++;endtask\n initial begin\n for(integer k=0;k<8192;k++)begin\n  cache_flush=f(k);managed_mode=f(k/4);transfer_discard=f(k/16);response_accept=f(k/64);ext_dma_wr_slot=(k/256)%2;\n  ext_dma_wr_col_base=(k/512)%SIZE;\n  for(integer j=0;j<2;j++)begin ext_dma_valid_cols_r[j]=$urandom_range(0,SIZE+LANES);ext_dma_logical_cols_r[j]=$urandom_range(0,SIZE+LANES);end\n  for(integer j=0;j<SIZE;j++)row_acc[j]=$urandom;\n  for(integer j=0;j<LANES;j++)begin ext_dma_wr_data[j]=$urandom;ext_dma_wr_valid[j]=f(k+j);end\n  if(k%8==0)for(integer j=0;j<LANES;j++)ext_dma_wr_valid[j]=0;\n  if(k%8==1)for(integer j=0;j<LANES;j++)ext_dma_wr_valid[j]=1;\n  if(k%8==2)ext_dma_wr_col_base='x;\n  if(k%8==3)ext_dma_wr_col_base='z;\n  if(k%8==4)ext_dma_wr_slot=1'bx;\n  if(k%8==5)ext_dma_valid_cols_r[0][k%32]=1'bx;\n  if(k%8==6)ext_dma_logical_cols_r[1][k%32]=1'bz;\n  if(k%8==7)begin ext_dma_wr_data[k%LANES][k%DATA_WIDTH]=1'bx;row_acc[k%SIZE][k%DATA_WIDTH]=1'bz;end\n  check();\n end\n $display("PASS checks=%0d",checks);$finish;end endmodule\n""")
    binary = folder / 'sim.vvp'
    with (folder / 'compile.log').open('w') as f:
        subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', str(binary), str(bench)], stdout=f, stderr=subprocess.STDOUT, check=True)
    r = subprocess.run(['vvp', str(binary)], text=True, capture_output=True, check=True, timeout=40)
    log = folder / 'run.log'
    log.write_text(r.stdout + r.stderr)
    row = {'passed': True, 'checks': int(next((x for x in r.stdout.splitlines() if x.startswith('PASS checks='))).split('=')[1])}
    row.update(SIZE=size, DATA_WIDTH=dw, BUS_WIDTH=bus, formal_log_sha256=digest(folder / 'formal.log'), run_log_sha256=digest(log))
    rows.append(row)
    print(json.dumps(row), flush=True)
(OUT / 'summary.json').write_text(json.dumps(dict(passed=True, profiles=rows, source_sha256={str(FOLDERS[label] / RTL): digest(FOLDERS[label] / RTL) for label in FOLDERS}), indent=2) + '\n')
