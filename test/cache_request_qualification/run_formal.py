from pathlib import Path
import argparse,json,hashlib,re,shlex,subprocess,sys
ROOT=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser();p.add_argument('--source-root',type=Path,required=True);p.add_argument('--reference-root',type=Path,required=True);p.add_argument('--profiles',nargs='+',default=['2:2:16:2:32:32:0','16:2:128:2:64:64:1']);p.add_argument('--seq',type=int,default=4);p.add_argument('--out',type=Path);args=p.parse_args()
out=args.out;out.mkdir(parents=True,exist_ok=True)
hashes={};records=[]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
for profile in args.profiles:
 names=['SETS','WAYS','LINE_BYTES','DEMAND_DEPTH','BUS_WIDTH','READ_WIDTH','p_defer_retire_shift'];params=dict(zip(names,map(int,profile.split(':'))));assert len(params)==7
 commands=[]
 for label,src in [('reference',args.reference_root),('current',args.source_root)]:
  files=[src/'rtl/npu/dma/cache/conv_read_cache.sv',src/'rtl/npu/dma/cache/conv_sdp_ram.sv',src/'rtl/npu/conv/conv_axi_span_reader.sv']+sorted(p for p in (src/'rtl/common').glob('*') if p.suffix in {'.v','.sv'})
  hashes.update({str(p):sha(p) for p in files})
  commands+=['read_slang -D SYNTHESIS=1 -D XILINX_FPGA=1 --top conv_read_cache '+ ' '.join(f'-G{k}={v}' for k,v in params.items())+' '+shlex.join(map(str,files)),'prep -top conv_read_cache -flatten','memory_map','async2sync','opt_clean', 'rename -hide w:*.valid_o_rd_data w:*.u_valid.o_rd_data w:*.valid_i_rd_addr w:*.u_valid.i_rd_addr','cd conv_read_cache']
  for slot in range(8):
   name=f'g_window.u_window.prefetch_selected_state_{slot}'
   if label=='reference':
    commands += [f'add -wire \\{name} 64', f'connect -set \\{name} \\g_window.u_window.u_prefetch_keys.mem[{slot}]']
   else:
    commands += [f'rename \\g_window.u_window.u_prefetch_selected.mem[{slot}] \\{name}']
  commands += ['cd ..',f'rename conv_read_cache {label}',f'design -stash {label}']
 commands+=['design -copy-from reference -as reference reference','design -copy-from current -as current current','equiv_make reference current equivalent','hierarchy -top equivalent','equiv_simple -short -seq 1','opt_clean',f'equiv_induct -seq {args.seq}','equiv_status -assert']
 stem=profile.replace(':','_');script=out/(stem+'.ys');log=out/(stem+'.log');script.write_text('\n'.join(commands)+'\n')
 with log.open('w') as stream:r=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],stdout=stream,stderr=subprocess.STDOUT,cwd=ROOT,timeout=1200)
 text=log.read_text();m=re.search(r'Of those cells (\d+) are proven and (\d+) are unproven',text)
 record={'parameters':params,'passed':r.returncode==0 and bool(m) and int(m[2])==0,'equivalent_bits':int(m[1]) if m else None,'unproven_bits':int(m[2]) if m else None,'log_sha256':sha(log)};records.append(record);print(json.dumps(record),flush=True)
 if not record['passed']:raise RuntimeError(f'{log}: returncode={r.returncode}')
assert hashes=={n:sha(Path(n)) for n in hashes}
(out/'summary.json').write_text(json.dumps({'passed':True,'inputs_constrained':False,'all_state_and_outputs':True,'source_sha256':hashes,'profiles':records},indent=2)+'\n')
