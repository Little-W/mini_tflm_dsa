#!/usr/bin/env python3
"""Build and run production PicoRV32/AXI/NPU SoC simulations."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import struct
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT))
from scripts.capacity.config import axi_data_width, selected_config
CPU_PROFILES = {
    'standard': {'cpu_enable_mul':1, 'cpu_enable_fast_mul':0, 'cpu_enable_div':1,
                 'cpu_enable_regs_dualport':1, 'cpu_two_stage_shift':1,
                 'cpu_barrel_shifter':0, 'cpu_two_cycle_compare':0, 'cpu_two_cycle_alu':0},
    'performance': {'cpu_enable_mul':1, 'cpu_enable_fast_mul':1, 'cpu_enable_div':1,
                    'cpu_enable_regs_dualport':1, 'cpu_two_stage_shift':1,
                    'cpu_barrel_shifter':1, 'cpu_two_cycle_compare':0, 'cpu_two_cycle_alu':0},
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2)+'\n')


def command(args, log, *, cwd=ROOT, timeout=1800):
    log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('w') as stream:
        stream.write('COMMAND: '+shlex.join([str(x) for x in args])+'\n');stream.flush()
        try:
            return subprocess.run([str(x) for x in args],cwd=cwd,stdout=stream,
                                  stderr=subprocess.STDOUT,timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            stream.write('\nHOST_TIMEOUT\n')
            return 124


def filelist_sources(path,cwd,picorv32):
    sources=[path];arguments=[];tokens=shlex.split(path.read_text(),comments=True);index=0
    while index<len(tokens):
        token=tokens[index]
        if token=='-f':
            index+=1
            nested_sources,nested_args=filelist_sources((cwd/tokens[index]).resolve(),cwd,picorv32)
            sources.extend(nested_sources);arguments.extend(nested_args)
        elif token.startswith('+incdir+'):
            arguments.append('+incdir+'+'+'.join(str((cwd/p).resolve()) for p in token[8:].split('+')))
        elif token.startswith(('+','-')):
            arguments.append(token)
        else:
            source=(cwd/token).resolve()
            if source.is_relative_to(ROOT/'picorv32'):
                source=picorv32/source.relative_to(ROOT/'picorv32')
            sources.append(source);arguments.append(str(source))
        index+=1
    return sources,arguments


def build_sim(out,verilator='verilator',jobs=1,*,skip=False,icache=1,ram_words=524288,pe_count=8,picorv32=None,
              ia_cache_blocks=8,ps_storage_rows=799,s16_output_banks=4,cpu_profile='performance',dma_max_bytes=None,bus_width=None,first_read_latency=8,ps_pool_bytes=0,
              shared_bank_bytes=None,shared_bank_count=None,im2col_cache_bytes=None):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    bus_width=axi_data_width(bus_width)
    selected=selected_config()
    shared_bank_bytes=selected['SHARED_BANK_BYTES'] if shared_bank_bytes is None else shared_bank_bytes
    shared_bank_count=selected['SHARED_BANK_COUNT'] if shared_bank_count is None else shared_bank_count
    im2col_cache_bytes=selected['IM2COL_CACHE_BYTES'] if im2col_cache_bytes is None else im2col_cache_bytes
    if (type(im2col_cache_bytes) is not int or not 512 <= im2col_cache_bytes <= 65536 or
            im2col_cache_bytes & (im2col_cache_bytes-1)):
        raise ValueError('IM2COL_CACHE_BYTES must be a power of two from 512 to 65536')
    if shared_bank_bytes not in (2048,4096,8192) or shared_bank_count not in range(6,10):
        raise ValueError('Shared RAM requires 2048, 4096 or 8192 bytes per bank and 6..9 banks')
    protocol_max_bytes=256*(bus_width//8)
    if dma_max_bytes is None:dma_max_bytes=protocol_max_bytes
    if (jobs<1 or pe_count not in (4,8) or icache not in (0,1) or ram_words<1 or
        ia_cache_blocks<1 or ps_storage_rows<0 or s16_output_banks<0 or cpu_profile not in CPU_PROFILES or
        bus_width not in (32,64) or ram_words*32%bus_width or dma_max_bytes!=protocol_max_bytes or first_read_latency<1):
        raise ValueError('Invalid simulator configuration')
    if ps_pool_bytes and (ps_pool_bytes < 64 or ps_pool_bytes % 64):
        raise ValueError('PS pool must contain complete 64-byte bank groups')
    if ps_pool_bytes:
        ia_cache_blocks=4
    if picorv32 is None:
        picorv32=os.environ.get('PICORV32_ROOT')
    if picorv32 is None:
        picorv32=ROOT/'picorv32'
        if not (picorv32/'picorv32.v').is_file():picorv32=ROOT.parent/'toolchains/picorv32'
    picorv32=Path(picorv32).resolve()
    cpu_commit=subprocess.check_output(['git','-C',picorv32,'rev-parse','HEAD'],text=True).strip()
    if cpu_commit!='ef203c2b0a3fb793280f5114941416c425c5b461':
        raise RuntimeError('PicoRV32 revision differs from the repository submodule')
    cwd=ROOT/'veri/sim';filelist=ROOT/'veri/flist/dut_axi_soc.f'
    sources,source_args=filelist_sources(filelist,cwd,picorv32)
    sources += [HERE/'tb_model_benchmark.sv',HERE/'sim_main.cpp',Path(__file__)]
    capture=ROOT/'test/ps_compression/ps_stream_capture.sv'
    if ps_pool_bytes:sources.append(capture)
    sources+=list((ROOT/'rtl/npu/ps_compact').glob('*.svh'))
    def hashes():
        return ({str(p.relative_to(ROOT)):digest(p) for p in sorted(set(sources)) if p.is_relative_to(ROOT)},
                {str(p):digest(p) for p in sorted(set(sources)) if not p.is_relative_to(ROOT)})
    before,external_before=hashes();binary=out/'obj/Vtb_model_benchmark';manifest_path=out/'build.json'
    profile={'size':16,'pe_count':pe_count,'ram_words':ram_words,'cpu_icache':icache,
             'ia_cache_blocks':ia_cache_blocks,'ps_frame_count':16,
             'ps_storage_rows':ps_storage_rows,'output_banks_s16_max':s16_output_banks,
             'matrix_tile_packed':True,'axi_read_outstanding':4,
             'axi_write_outstanding':4,'dma_max_bytes':dma_max_bytes,'core':'unified','pcr_engine':0,
             'ps_compress':bool(ps_pool_bytes),'ps_pool_bytes':ps_pool_bytes,
             'data_width':16,'weight_width':16,'dw_max_taps':49,
             'pool_max_taps':256,'ram_read_first_latency':first_read_latency,
             'ram_read_latency_origin':'accepted_AR','ram_continuous_read_beat_cycles':1,'bus_width':bus_width,'cpu_axi_data_bits':32,'rounding_mode':'nearest_even',
             'vector_engine':'VCE','add_s8':True,'softmax_s8':True,'capability_version':1,
             'conv_cache_data_bytes':im2col_cache_bytes,'conv_cache_policy':'windowed',
             'im2col_cache_bytes':im2col_cache_bytes,
             'conv_cache_prefetch':True,'vector_line_cache_bytes':0,
             'conv_cache_demand_outstanding':4,'vector_window_outstanding':4,
             'im2col_corrected_elements_per_cycle':4,
             'cpu':'PicoRV32','cpu_profile':cpu_profile,**CPU_PROFILES[cpu_profile],
             'cpu_isa':'RV32IM','cpu_compressed_isa':0,
             'cpu_icache_lines':64,'cpu_icache_line_words':4,
             'cpu_icache_data_bytes':1024 if icache else 0,
             'cpu_axi_read_timing_buffer':1,'cpu_axi_write_timing_buffer':1,
             'npu_axi_timing_buffer':1,'bypass_ram_pingpong':1,'ram_write_timing_buffer':1}
    shared_total = shared_bank_bytes * shared_bank_count
    shared_enabled = bool(ps_pool_bytes)
    profile.update(shared_ia_ps=shared_enabled,
        shared_total_bytes=shared_total if shared_enabled else 0,
        shared_bank_bytes=shared_bank_bytes if shared_enabled else 0,
        shared_bank_count=shared_bank_count if shared_enabled else 0,
        shared_ia_bank_choices=[1, 2, 4] if shared_enabled else [],
        ps_directory_rows=1024 if shared_enabled else 0)
    if skip:
        manifest=json.loads(manifest_path.read_text())
        if (manifest.get('returncode')!=0 or manifest.get('source_sha256')!=before or
            manifest.get('external_dependency_sha256')!=external_before or
            manifest.get('profile')!=profile or digest(binary)!=manifest.get('binary_sha256')):
            raise RuntimeError('Simulator sources, parameters or executable differ from saved build')
        return binary
    args=[verilator,'--cc','--exe','--assert','-sv',
          '--top-module','tb_model_benchmark','-Wno-fatal','--Mdir',out/'obj','-j',jobs,
          '--output-groups','0','--output-split','12000',
          '-CFLAGS','-std=c++17 --param=ggc-min-expand=5 --param=ggc-min-heapsize=4096',
          f'-DSOC_NETWORK_RAM_WORDS={ram_words}',f'-DSOC_NETWORK_ICACHE={icache}',
          f'-DSOC_NETWORK_DMA_MAX_BYTES={dma_max_bytes}',f'-DSOC_NETWORK_BUS_WIDTH={bus_width}',
          f'-DSOC_NETWORK_READ_FIRST_LATENCY={first_read_latency}',
          f'-DSOC_NETWORK_SHARED_BANK_BYTES={shared_bank_bytes}',
          f'-DSOC_NETWORK_SHARED_BANK_COUNT={shared_bank_count}',
          f'-DSOC_NETWORK_IM2COL_CACHE_BYTES={im2col_cache_bytes}',
          *[f'-DSOC_NETWORK_{key.upper()}={value}' for key,value in CPU_PROFILES[cpu_profile].items()],
          f'-DSOC_NETWORK_IA_CACHE_BLOCKS={ia_cache_blocks}',
          f'-DSOC_NETWORK_PS_STORAGE_ROWS={ps_storage_rows}',
          f'-DSOC_NETWORK_S16_OUTPUT_BANKS={s16_output_banks}',
          f'-DSOC_NETWORK_PE_COUNT={pe_count}',
          *([f'-DGEMMORA_PS_POOL_BYTES={ps_pool_bytes}','-DGEMPACT_PS_COMPRESS',str(capture)] if ps_pool_bytes else []),
          *source_args,
          HERE/'tb_model_benchmark.sv',HERE/'sim_main.cpp']
    rc=command(args,out/'elaborate.log',cwd=cwd)
    compile_args=['make','-C',out/'obj','-f','Vtb_model_benchmark.mk','-j',jobs,
                  'OPT_FAST=-O3','OPT_SLOW=-O0','OPT_GLOBAL=-O3',
                  'VK_PCH_I_FAST=','VK_PCH_I_SLOW=','CFG_CXXFLAGS_PCH=-E']
    if rc==0:rc=command(compile_args,out/'compile.log',cwd=cwd,timeout=7200)
    manifest={'returncode':rc,'profile':profile,'source_sha256':before,
              'configuration':profile,'external_dependency_sha256':external_before,
              'sources_unchanged_during_build':(before,external_before)==hashes(),
              'command':[str(x) for x in args],'compile_command':[str(x) for x in compile_args],
              'verilator':subprocess.check_output([verilator,'--version'],text=True).strip(),
              'picorv32_commit':cpu_commit,'picorv32_path':str(picorv32)}
    if rc==0:manifest['binary_sha256']=digest(binary)
    write_json(manifest_path,manifest)
    if rc or not manifest['sources_unchanged_during_build']:
        log=out/('compile.log' if (out/'compile.log').is_file() else 'elaborate.log')
        raise RuntimeError('SoC build did not complete successfully: '+str(log)+'\n'+log.read_text()[-4000:])
    return binary


def parse_log(path):
    text=Path(path).read_text();counters=[];window_jobs=[];cpu_profiles=[];dma_profiles=[]
    for line in text.splitlines():
        if line.startswith('SOC_NETWORK_CPU_PROFILE '):
            cpu_profiles.append({key:int(value) for key,value in re.findall(r'(\w+)=([^\s]+)',line)})
            continue
        if line.startswith('SOC_NETWORK_DMA_PROFILE '):
            dma_profiles.append({key:int(value) for key,value in re.findall(r'(\w+)=([^\s]+)',line)})
            continue
        if line.startswith('SOC_NETWORK_WINDOW_JOB '):
            window_jobs.append({key:int(value) for key,value in re.findall(r'(\w+)=([^\s]+)',line)})
            continue
        if not line.startswith('SOC_NETWORK_COUNTER '):continue
        values=dict(re.findall(r'(\w+)=([^\s]+)',line))
        counters.append({key:(value if key=='scope' else int(value)) for key,value in values.items()})
    return {'passed':'SOC_NETWORK_PASS ' in text and '%Error' not in text,
            'counters':counters,'window_jobs':window_jobs,'cpu_profiles':cpu_profiles,'dma_profiles':dma_profiles}


def pack_memory_images(firmware, data, output, *, ram_words, data_base_word=0):
    """Overlay sparse 32-bit images, then form little-endian 64-bit RAM rows."""
    words={}
    for path,start in ((firmware,0),(data,data_base_word)):
        if path is None:continue
        content=re.sub(r'/\*.*?\*/|//[^\n]*','',Path(path).read_text(),flags=re.S)
        address=start
        for token in content.split():
            if token.startswith('@'):
                address=int(token[1:],16)
                continue
            value=int(token.replace('_',''),16)
            if value<0 or value>0xffffffff or not 0<=address<ram_words:
                raise ValueError(f'Invalid 32-bit memory word at {address:#x} in {path}')
            words[address]=value
            address+=1
    rows={}
    for address,value in words.items():
        index=address//2
        rows[index]=rows.get(index,0)|(value<<(32*(address%2)))
    with Path(output).open('w') as stream:
        previous=-2
        for index,value in sorted(rows.items()):
            if index!=previous+1:stream.write(f'@{index:08x}\n')
            stream.write(f'{value:016x}\n')
            previous=index


def run_sim(binary,out,mem,*,data_mem=None,result_addr=0,result_words=26,
            output_addr=0,output_bytes=0,output_addr_word=15,output_bytes_word=14,
            trace_addr=0,timeout_cycles=4000000000,timeout_seconds=7200,
            ram_fixed_lat=0,network_begin=0xc0f10001,network_end=0xc0f10002,
            tensor_marker=0xc0f20000,expected_status=0,extra_plusargs=()):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((Path(binary).resolve().parents[1]/'build.json').read_text())
    profile=manifest['profile']
    memory_path=Path(mem).resolve()
    packed_memory=None
    if profile['bus_width']==64:
        base_word=0
        for argument in extra_plusargs:
            if argument.startswith('+SOC_DATA_MEM_BASE_WORD='):
                base_word=int(argument.split('=',1)[1],0)
        memory_path=out/'memory_axi64.mem'
        pack_memory_images(mem,data_mem,memory_path,ram_words=profile['ram_words'],data_base_word=base_word)
        packed_memory={'path':str(memory_path),'sha256':digest(memory_path),'word_bits':64}
    args=[str(binary),f'+SOC_CPU_MEM={memory_path}',f'+TIMEOUT_CYCLES={timeout_cycles}', 
          f'+RAM_FIXED_LAT={ram_fixed_lat}',
          f'+RAM_READ_FIRST_LATENCY={profile.get("ram_read_first_latency",2)}',f'+NETWORK_BEGIN={network_begin:08x}',
          f'+NETWORK_END={network_end:08x}',f'+TENSOR_MARKER={tensor_marker:08x}',
          f'+RESULT_ADDR={result_addr:08x}',f'+RESULT_WORDS={result_words}',
          f'+RESULT_FILE={out/"result.bin"}',f'+OUTPUT_ADDR={output_addr:08x}',
          f'+OUTPUT_BYTES={output_bytes}',f'+OUTPUT_ADDR_WORD={output_addr_word}',
          f'+OUTPUT_BYTES_WORD={output_bytes_word}',f'+OUTPUT_FILE={out/"output.bin"}',
          f'+EXPECTED_STATUS={expected_status}']
    if data_mem is not None and profile['bus_width']==32:args.append(f'+SOC_DATA_MEM={Path(data_mem).resolve()}')
    if trace_addr:
        (out/'tensors').mkdir(exist_ok=True)
        args.extend([f'+TRACE_ADDR={trace_addr:08x}',f'+TRACE_DIR={out/"tensors"}',f'+TRACE_FILE={out/"trace.txt"}'])
    args.extend(extra_plusargs)
    rc=command(args,out/'run.log',timeout=timeout_seconds)
    report=parse_log(out/'run.log');report['returncode']=rc;report['passed']&=rc==0
    expected_cpu={key:profile[key] for key in CPU_PROFILES[profile['cpu_profile']]}
    expected_cpu['cpu_icache']=profile['cpu_icache']
    report['cpu_profile_matches_build']=report['cpu_profiles']==[expected_cpu]
    report['passed']&=report['cpu_profile_matches_build']
    report['dma_bursts_within_limit']=(len(report['dma_profiles'])==1 and
        report['dma_profiles'][0]['dma_max_bytes']==profile['dma_max_bytes'] and
        report['dma_profiles'][0]['bus_width']==profile['bus_width'] and
        report['dma_profiles'][0]['read_first_latency']==profile['ram_read_first_latency'] and
        report['dma_profiles'][0]['observed_ram_first_min']>=profile['ram_read_first_latency'] and
        report['dma_profiles'][0]['max_read_burst_bytes']<=profile['dma_max_bytes'] and
        report['dma_profiles'][0]['max_write_burst_bytes']<=profile['dma_max_bytes'])
    report['passed']&=report['dma_bursts_within_limit']
    if packed_memory is not None:report['packed_memory']=packed_memory
    report['command']=args;report['simulator_sha256']=digest(binary);report['firmware_memory_sha256']=digest(mem)
    if data_mem is not None:report['data_memory_sha256']=digest(data_mem)
    if (out/'result.bin').exists():
        raw=(out/'result.bin').read_bytes();report['result_words']=[v[0] for v in struct.iter_unpack('<I',raw)]
        report['result_sha256']=digest(out/'result.bin')
    if (out/'output.bin').exists():report['output_sha256']=digest(out/'output.bin')
    write_json(out/'summary.json',report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir',type=Path,required=True)
    parser.add_argument('--verilator',default='verilator')
    parser.add_argument('--jobs',type=int,default=1)
    parser.add_argument('--skip-build',action='store_true')
    parser.add_argument('--build-only',action='store_true')
    parser.add_argument('--icache',type=int,choices=[0,1],default=1)
    parser.add_argument('--cpu-profile',choices=CPU_PROFILES,default='performance')
    parser.add_argument('--first-read-latency',type=int,default=8)
    parser.add_argument('--bus-width',type=int,choices=(32,64))
    parser.add_argument('--shared-bank-bytes',type=int,choices=(2048,4096,8192))
    parser.add_argument('--shared-bank-count',type=int,choices=range(6,10))
    parser.add_argument('--im2col-cache-bytes',type=int,
                        help='Input window cache bytes; default comes from NPU_CONFIG')
    parser.add_argument('--ram-words',type=int,default=524288)
    parser.add_argument('--pe-count',type=int,default=8)
    parser.add_argument('--ia-cache-blocks',type=int,default=8)
    parser.add_argument('--ps-storage-rows',type=int,default=799)
    parser.add_argument('--s16-output-banks',type=int,default=4)
    parser.add_argument('--ps-pool-bytes',type=int,default=0)
    parser.add_argument('--picorv32',type=Path)
    parser.add_argument('--out',type=Path)
    parser.add_argument('--mem',type=Path)
    parser.add_argument('--data-mem',type=Path)
    parser.add_argument('--result-addr',type=lambda x:int(x,0),default=0)
    parser.add_argument('--result-words',type=int,default=26)
    parser.add_argument('--output-addr',type=lambda x:int(x,0),default=0)
    parser.add_argument('--output-bytes',type=int,default=0)
    parser.add_argument('--output-addr-word',type=int,default=15)
    parser.add_argument('--output-bytes-word',type=int,default=14)
    parser.add_argument('--trace-addr',type=lambda x:int(x,0),default=0)
    parser.add_argument('--timeout-cycles',type=int,default=4000000000)
    parser.add_argument('--timeout-seconds',type=int,default=7200)
    parser.add_argument('--ram-fixed-lat',type=int,default=0)
    parser.add_argument('--plusarg',action='append',default=[])
    args=parser.parse_args()
    binary=build_sim(args.build_dir,args.verilator,args.jobs,skip=args.skip_build,
                     icache=args.icache,ram_words=args.ram_words,pe_count=args.pe_count,picorv32=args.picorv32,
                     ia_cache_blocks=args.ia_cache_blocks,ps_storage_rows=args.ps_storage_rows,
                     s16_output_banks=args.s16_output_banks,cpu_profile=args.cpu_profile,
                     bus_width=args.bus_width,first_read_latency=args.first_read_latency,
                     ps_pool_bytes=args.ps_pool_bytes,shared_bank_bytes=args.shared_bank_bytes,
                     shared_bank_count=args.shared_bank_count,im2col_cache_bytes=args.im2col_cache_bytes)
    if args.build_only:print(binary);return 0
    if args.out is None or args.mem is None:parser.error('--out and --mem are required for execution')
    report=run_sim(binary,args.out,args.mem,data_mem=args.data_mem,result_addr=args.result_addr,
                   result_words=args.result_words,output_addr=args.output_addr,output_bytes=args.output_bytes,
                   output_addr_word=args.output_addr_word,output_bytes_word=args.output_bytes_word,
                   trace_addr=args.trace_addr,timeout_cycles=args.timeout_cycles,timeout_seconds=args.timeout_seconds,
                   ram_fixed_lat=args.ram_fixed_lat,extra_plusargs=args.plusarg)
    print(json.dumps({'passed':report['passed'],'summary':str(args.out/'summary.json')}))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
