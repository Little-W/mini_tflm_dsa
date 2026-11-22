"""检查实际加载器需求接收和预取选择的全部输入关系。"""
from pathlib import Path
import argparse, hashlib, json, subprocess, sys
ROOT = Path(__file__).resolve().parents[2]
RTL = Path('rtl/npu/loaders/kernel_loader.sv')
p = argparse.ArgumentParser()
p.add_argument('--source-root', type=Path, default=ROOT)
p.add_argument('--reference-root', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
args = p.parse_args()
OUT = args.out
OUT.mkdir(parents=True, exist_ok=True)
FOLDERS = {'reference': args.reference_root, 'current': args.source_root}

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def model(name, text):
    marker = '  // 控制器提供未发起的需求' if name == 'current' else '  assign ctrl_buf_load_ready'
    start = text.index(marker)
    end = text.index('  assign response_accept', start)
    body = text[start:end]
    return f"module {name}(input wire[16:0] stimulus,output wire[11:0] result);\n localparam logic[1:0] PF_EMPTY=0,PF_PENDING=1,PF_LOADING=2,PF_CACHED=3;\n wire command_mode_q=stimulus[0];wire[1:0] prefetch_state=stimulus[2:1];\n wire transfer_active=stimulus[3],transfer_prefetch=stimulus[4],demand_confirmed=stimulus[5];\n wire pending=stimulus[6],buf_load_ready=stimulus[7],command_waiting=stimulus[8];\n wire ext_dma_busy=stimulus[9],cache_flush=stimulus[10],init_cfg=stimulus[11];\n wire comparison_stored_ready=stimulus[12],comparison_match_q=stimulus[13];\n wire buf_load_commit=stimulus[14],buf_discard_ready=stimulus[15],load_weight_granted=stimulus[16];\n wire managed_mode=command_mode_q || prefetch_state!=PF_EMPTY || (transfer_active && transfer_prefetch);\n wire ctrl_o_request_pending=!cache_flush && pending;\n logic ctrl_buf_load_ready,ctrl_load_req,ctrl_load_granted,ctrl_i_request_open,ctrl_i_request_accept;\n logic managed_demand_available,unmanaged_demand_available,prefetch_available,managed_demand_granted;\n logic cache_hit_fire,discard_fire,buf_discard_head,demand_issue,prefetch_issue;\n logic managed_prefetch_available,managed_request_available,selected_request_available,selected_prefetch;\n logic request_permitted,load_weight_req,cache_data_available,demand_data_available,managed_grant_ready,unmanaged_grant_ready;\n logic dma_start,prefetch_dma_start,demand_dma_start,buf_load_start;\n wire load_idle_o_start=load_weight_req && load_weight_granted;\n {('assign ctrl_load_req=ctrl_o_request_pending && ctrl_buf_load_ready;' if name == 'reference' else '')}\n {body}\n assign result={{load_weight_req,selected_prefetch,prefetch_issue,dma_start,prefetch_dma_start,\n    demand_dma_start,cache_hit_fire,discard_fire,buf_discard_head,buf_load_start,ctrl_load_req,\n    {('ctrl_load_req && ctrl_load_granted' if name == 'reference' else 'ctrl_o_request_pending && ctrl_i_request_accept')}}};\nendmodule\n"
models = '\n'.join((model(label, (FOLDERS[label] / RTL).read_text()) for label in ['reference', 'current']))
rows = []
for synthesis in [False, True]:
    folder = OUT / ('synthesis' if synthesis else 'simulation')
    folder.mkdir(exist_ok=True)
    defines = '`define SYNTHESIS 1\n' if synthesis else ''
    formal = folder / 'formal.sv'
    formal.write_text(defines + models + 'module formal(input wire[16:0]stimulus,output wire equivalent);\n wire[11:0]a,b;reference r(stimulus,a);current c(stimulus,b);assign equivalent=a==b;endmodule\n')
    ys = folder / 'prove.ys'
    ys.write_text(f'read_slang --top formal {formal}\nprep -top formal -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
    with (folder / 'formal.log').open('w') as f:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'), '--worker', str(ys)], stdout=f, stderr=subprocess.STDOUT, check=True, timeout=30)
    bench = folder / 'tb.sv'
    bench.write_text(defines + models + 'module tb;\n logic[16:0]stimulus,saved;wire[11:0]a,b;integer checks=0;\n reference r(stimulus,a);current c(stimulus,b);\n function automatic logic state_bit(input integer x);case(x)0:return 1\'b0;1:return 1\'b1;2:return 1\'bx;default:return 1\'bz;endcase endfunction\n task compare;#1;if(a!==b)$fatal(1,"接收控制不同 stimulus=%b ref=%b cur=%b",stimulus,a,b);checks++;endtask\n initial begin\n  stimulus=\'0;compare();stimulus=\'1;compare();stimulus=\'x;compare();stimulus=\'z;compare();\n  for(integer trial=0;trial<65536;trial++)begin\n   stimulus=\'0;stimulus[16:12]=\'1;\n   for(integer i=0;i<8;i++)stimulus[i]=state_bit((trial>>(2*i))&3);\n   compare();\n  end\n  for(integer trial=0;trial<4096;trial++)begin stimulus=$urandom;compare();end\n  for(integer trial=0;trial<64;trial++)begin\n   stimulus=$urandom;saved=stimulus;\n   for(integer i=0;i<17;i++)begin stimulus=saved;stimulus[i]=1\'bx;compare();stimulus[i]=1\'bz;compare();end\n  end\n  $display("{\\"passed\\":true,\\"checks\\":%0d}",checks);$finish;\n end\nendmodule\n')
    binary = folder / 'sim.vvp'
    with (folder / 'compile.log').open('w') as f:
        subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', str(binary), str(bench)], stdout=f, stderr=subprocess.STDOUT, check=True)
    r = subprocess.run(['vvp', str(binary)], text=True, capture_output=True, check=True, timeout=60)
    log = folder / 'run.log'
    log.write_text(r.stdout + r.stderr)
    row = json.loads(next((line for line in r.stdout.splitlines() if line.startswith('{'))))
    row.update(synthesis=synthesis, formal_log_sha256=digest(folder / 'formal.log'), run_log_sha256=digest(log))
    rows.append(row)
    print(json.dumps(row), flush=True)
(OUT / 'summary.json').write_text(json.dumps({'passed': True, 'profiles': rows, 'source_sha256': {str(FOLDERS[label] / RTL): digest(FOLDERS[label] / RTL) for label in ['reference', 'current']}}, indent=2) + '\n')
