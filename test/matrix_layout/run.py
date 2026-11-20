#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Exercise packed GEMM/Conv, fixed PS capacity, and S16 FIFO backpressure."""
from __future__ import annotations
import argparse
import hashlib
import json
import random
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'veri/top_regression'))
from host_tiling import plan

SIZE, WORDS = 16, 131072
SENTINEL = bytes.fromhex('c33ca55a')


def rne(value: int, amount: int) -> int:
    """Integer division rounded to nearest, with even results at exact halves."""
    if amount <= 0:
        return value
    quotient, remainder = divmod(value, 1 << amount)
    half = 1 << (amount - 1)
    return quotient + int(remainder > half or (remainder == half and quotient % 2))


def requant(value: int, multiplier: int, shift: int, output16: bool) -> int:
    if output16:
        reduced = min(32767, rne(multiplier, 16))
        return rne(value * reduced, min(63, max(0, 15 - shift)))
    return rne(value * multiplier, 31 - shift)


def sparse_words(path: Path, image: bytes) -> None:
    lines, previous = [], -2
    for word in range(len(image) // 4):
        value = image[4 * word:4 * word + 4]
        if value != SENTINEL:
            if word != previous + 1:
                lines.append(f'@{word:x}')
            lines.append(f'{int.from_bytes(value, "little"):08x}')
            previous = word
    path.write_text('\n'.join(lines) + '\n')


def sparse_access(path: Path, access: bytearray) -> None:
    lines, previous = [], -2
    for address, value in enumerate(access):
        if value:
            if address != previous + 1:
                lines.append(f'@{address:x}')
            lines.append(str(value))
            previous = address
    path.write_text('\n'.join(lines) + '\n')


def case(out: Path, name: str, ia: int, *, m=17, n=23, k=19, layout=3,
         mode=0, input16=False, output16=False, channel=True, zp=True,
         requested_r=2, requested_w=2, error=0, injection=0, hold=0,
         require_full=False, check_busy=False, crossing=False, conv=False,
         exact_reuse=False, injection_address=0, rounding_ties=False, seed=1) -> Path:
    directory = out / name
    directory.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    if output16:
        input16 = True
    input_bytes, output_bytes = (2 if input16 else 1), (2 if output16 else 1)
    a_base, b_base, bias_base, mult_base, shift_base, dst = 0x0ff0, 0x11ff0, 0x21000, 0x22000, 0x23000, 0x30ff0
    image = bytearray(SENTINEL * WORDS)
    access = bytearray(4 * WORDS)
    a_stride = ((k * input_bytes + 3) // 4) * 4 + 12
    b_stride = ((k + 3) // 4) * 4 + 8
    dst_stride = ((n * output_bytes + 3) // 4) * 4 + 4
    a_offset, b_offset = ((-3, 5) if zp else (0, 0))
    if conv:
        b_offset = 0
    dst_offset = 0 if output16 else -7
    amin, amax = (-20000, 19000) if output16 else (-111, 109)
    value_limit = 1200 if output16 else (500 if input16 else 11)
    a = [[rng.randint(-value_limit, value_limit) for _ in range(k)] for _ in range(m)]
    b = [[rng.randint(-11, 11) for _ in range(k)] for _ in range(n)]
    bias = [rng.randint(-10000, 10000) if output16 else rng.randint(-500, 500) for _ in range(n)]
    shifts = [(-2 if output16 else -9 if input16 else -3) - (j % 3 if channel else 0) for j in range(n)]
    multipliers = [(1 << 30) + ((j % 3) * (1 << 27) if channel else 0) for j in range(n)]
    if rounding_ties:
        assert (m,n,k)==(1,6,1) and not channel and not zp
        a=[[1]];b=[[v] for v in [-80,-48,-16,16,48,80]];bias=[0]*n
        shifts=[-4]*n;multipliers=[1<<30]*n;dst_offset=0

    def put(address: int, value: int, width: int) -> None:
        image[address:address + width] = (value & ((1 << (8 * width)) - 1)).to_bytes(width, 'little')

    def store_operand(base: int, matrix: list[list[int]], width: int, packed: bool, stride: int) -> dict:
        rows = len(matrix)
        reduction_tiles = (k + SIZE - 1) // SIZE
        size = ((rows + SIZE - 1) // SIZE) * reduction_tiles * SIZE * SIZE * width if packed else rows * stride
        if packed:
            image[base:base + size] = b'\x5a' * size
        for row in range(rows):
            if packed:
                for kt in range(reduction_tiles):
                    address = base + (((row // SIZE) * reduction_tiles + kt) * SIZE * SIZE + (row % SIZE) * SIZE) * width
                    access[address:address + SIZE * width] = b'\x01' * (SIZE * width)
            else:
                address = base + row * stride
                valid_bytes = ((k * width + 3) // 4) * 4
                access[address:address + valid_bytes] = b'\x01' * valid_bytes
            for red, value in enumerate(matrix[row]):
                offset = (((row // SIZE) * reduction_tiles + red // SIZE) * SIZE * SIZE + (row % SIZE) * SIZE + red % SIZE) * width if packed else row * stride + red * width
                put(base + offset, value, width)
        return dict(base=base, bytes=size, rows=rows, reduction=k, element_bytes=width,
                    layout='tile_row_reduction_row_col' if packed else 'row_major_with_stride')

    conv_fields = {}
    if conv:
        # NHWC 5x5x3, 3x3 SAME, output 5x5x19. Padding becomes zero after
        # input correction, matching the mathematical im2col matrix below.
        assert (m, n, k) == (25, 19, 27)
        h, w, c, kh, kw, oh, ow = 5, 5, 3, 3, 3, 5, 5
        raw = [rng.randint(-11, 11) for _ in range(h * w * c)]
        image[a_base:a_base + len(raw)] = bytes(v & 255 for v in raw)
        access[a_base:a_base + len(raw)] = b'\x01' * len(raw)
        a = []
        for oy in range(oh):
            for ox in range(ow):
                row = []
                for ky in range(kh):
                    for kx in range(kw):
                        iy, ix = oy + ky - 1, ox + kx - 1
                        for ci in range(c):
                            row.append(raw[(iy * w + ix) * c + ci] if 0 <= iy < h and 0 <= ix < w else -a_offset)
                a.append(row)
        a_info = dict(base=a_base, bytes=len(raw), layout='NHWC', shape=[h,w,c])
        conv_fields = {32:1,33:a_base,34:h,35:w,36:c,37:c,39:kh,40:kw,41:oh,42:ow,
                       43:1,44:1,45:1,46:1,47:1,48:1,49:a_offset}
        # The corrected im2col stream is signed 16-bit; external input is s8.
        input16 = True
        a_stride = ((k + SIZE - 1) // SIZE) * SIZE * 2
    else:
        a_info = store_operand(a_base, a, input_bytes, bool(layout & 1), a_stride)
    b_info = store_operand(b_base, b, 1, bool(layout & 2), b_stride)
    for j in range(n):
        put(bias_base + 4*j, bias[j], 4)
        if channel:
            put(mult_base + 4*j, multipliers[j], 4)
            put(shift_base + 4*j, shifts[j], 4)
    access[bias_base:bias_base+4*n] = b'\x01'*(4*n)
    if channel:
        access[mult_base:mult_base+4*n] = b'\x01'*(4*n)
        access[shift_base:shift_base+4*n] = b'\x01'*(4*n)
    golden = bytearray(image)
    expected_output = bytearray()
    for row in range(m):
        for col in range(n):
            value = bias[col] + sum((av + a_offset) * (bv + b_offset) for av, bv in zip(a[row], b[col]))
            assert -(1 << 31) <= value < (1 << 31)
            value = requant(value, multipliers[col], shifts[col], output16) + dst_offset
            value = max(amin, min(amax, value))
            value = max(-32768 if output16 else -128, min(32767 if output16 else 127, value))
            encoded = (value & ((1 << (8*output_bytes))-1)).to_bytes(output_bytes,'little')
            address = dst + row * dst_stride + col * output_bytes
            access[address:address+output_bytes] = b'\x02'*output_bytes
            if error == 0 or injection == 2:
                golden[address:address+output_bytes] = encoded
            expected_output.extend(encoded)
    p = plan(m,n,SIZE,ia,16,requested_r,requested_w,bool(mode and not output16),channel)
    if exact_reuse:
        sr,sc=(n,m) if mode and not output16 else (m,n)
        tr,tc=(sr+SIZE-1)//SIZE,(sc+SIZE-1)//SIZE
        assert requested_r<=min(tr,ia//2) and requested_w<=min(tc,16)
        p=dict(ia_reuse=requested_r,w_reuse=requested_w,
               row_groups=(tr+requested_r-1)//requested_r,
               row_tail_tiles=(tr-1)%requested_r+1,
               col_groups=(tc+requested_w-1)//requested_w,
               col_tail_tiles=(tc-1)%requested_w+1)
    config = [0]*64
    values = {0:0x4e505531,1:SIZE,2:ia,3:m,4:k,5:n,6:p['ia_reuse'],7:p['w_reuse'],8:mode,9:16,
              10:WORDS,11:WORDS,12:int(input16),13:int(channel),14:a_base,15:b_base,16:bias_base,
              17:dst,18:a_stride,19:b_stride,20:dst_stride,21:0 if conv else a_offset,22:b_offset,23:dst_offset,
              24:mult_base if channel else multipliers[0],25:shift_base if channel else shifts[0],26:amin,27:amax,
              28:int(output16),29:layout,30:p['row_groups']|(p['col_groups']<<16),
              31:p['row_tail_tiles']|(p['col_tail_tiles']<<16),52:error,53:injection,
              54:hold,55:int(check_busy),56:int(require_full),57:int(crossing),58:int(crossing),
              59:injection_address,**conv_fields}
    for index,value in values.items():
        config[index]=value&0xffffffff
    (directory/'config.mem').write_text(''.join(f'{v:08x}\n' for v in config))
    sparse_words(directory/'init.mem',image)
    sparse_words(directory/'golden.mem',golden)
    sparse_access(directory/'access.mem',access)
    metadata = dict(name=name,M=m,N=n,K=k,layout_flags=layout,
                    dataflow='IS' if mode and not output16 else 'WS',
                    requested_dataflow='IS' if mode else 'WS',input16=input16,
                    output16=output16,per_channel=channel,lhs_offset=a_offset,rhs_offset=b_offset,
                    output_offset=dst_offset,seed=seed,tiling=p,ps_required_rows=((p['ia_reuse']+1)*SIZE-1)*(p['w_reuse']+1),
                    expected_error=error,injection=injection,write_hold_cycles=hold,check_busy=check_busy,
                    injection_address=injection_address,rounding_ties=rounding_ties,
                    operands=[a_info,b_info],output_sha256=hashlib.sha256(expected_output).hexdigest(),
                    memory_guard='all non-output bytes; packed unused rows forbidden on AR',
                    reference='Python unbounded integer dot product and integer RNE')
    (directory/'case.json').write_text(json.dumps(metadata,indent=2)+'\n')
    return directory


def cases(out: Path, ia: int, compact: bool) -> list[Path]:
    result=[]
    def add(name,**kwargs):
        result.append(case(out,name,ia,seed=1000+len(result),**kwargs))
    for mode in (0,1):
        for layout in (0,1,2,3):
            add(f's8_tail_mode{mode}_layout{layout}',layout=layout,mode=mode,crossing=bool(layout),check_busy=True)
            if not compact and layout:
                add(f's8_tile_mode{mode}_layout{layout}',m=16,n=16,k=16,layout=layout,mode=mode,channel=False,zp=False)
                add(f's8_groups_mode{mode}_layout{layout}',m=49,n=37,k=35,layout=layout,mode=mode,requested_r=min(4,ia//2))
        for layout in ((3,) if compact else (1,2,3)):
            add(f's16_input_mode{mode}_layout{layout}',layout=layout,mode=mode,input16=True)
        add(f'conv_rhs_packed_mode{mode}',m=25,n=19,k=27,layout=2,mode=mode,conv=True)
        add(f'conv_lhs_packed_reject_mode{mode}',m=25,n=19,k=27,layout=3,mode=mode,conv=True,error=1)
        add(f'read_error_mode{mode}',mode=mode,error=3,injection=1)
        add(f'write_error_mode{mode}',mode=mode,error=3,injection=2)
        add(f'recovery_mode{mode}',mode=mode,layout=1,zp=True)
    for layout in ((3,) if compact else (0,1,2,3)):
        add(f's16_output_tail_layout{layout}',layout=layout,output16=True)
    add('s16_fifo_backpressure',m=64,n=64,k=33,layout=3,output16=True,
        requested_r=min(4,ia//2),requested_w=4,hold=12000,require_full=True,check_busy=True)
    for output16 in (False,True):
        add(f'rne_ties_output16_{int(output16)}',m=1,n=6,k=1,layout=3,
            output16=output16,zp=False,channel=False,rounding_ties=True)
    add('s16_read_error',output16=True,error=3,injection=1)
    add('s16_write_error',output16=True,error=3,injection=2)
    add('s16_after_error',output16=True,layout=2)
    add('s16_output_forced_ws',mode=1,output16=True,layout=3)
    add('s16_output_forced_ws_ps799',m=32,n=256,k=17,mode=1,output16=True,
        layout=3,requested_r=2,requested_w=16)
    add('is_bias_tail_error',mode=1,error=3,injection=1,injection_address=0x21040)
    add('is_after_bias_tail_error',mode=1,layout=2)
    # The PS payload is exactly (47 rows/frame)*(17 frames) = 799 rows.
    add('ps799_exact_ws',m=32,n=256,k=17,layout=3,requested_r=2,requested_w=16)
    add('ps799_exact_is',m=256,n=32,k=17,layout=3,mode=1,requested_r=2,requested_w=16)
    if ia>=8:
        add('s16_output_forced_ws_capacity',m=64,n=256,k=17,mode=1,output16=True,
            layout=3,requested_r=4,requested_w=16,error=1)
        add('s16_output_after_mode_capacity',mode=1,output16=True,layout=3)
        for m,n,k,r,w in [(1,64,17,4,1),(1,63,40,4,1),(17,64,40,4,1),(17,63,17,4,2)]:
            for layout in (0,2,3):
                add(f'is_r{r}_w{w}_m{m}_n{n}_k{k}_layout{layout}',m=m,n=n,k=k,
                    mode=1,layout=layout,requested_r=r,requested_w=w,exact_reuse=True)
        add('ps799_exceeded_ws',m=64,n=256,k=17,layout=3,requested_r=4,requested_w=16,error=1)
        add('after_capacity_error_ws',layout=2)
        add('ps799_exceeded_is',m=256,n=64,k=17,layout=3,mode=1,requested_r=4,requested_w=16,error=1)
        add('after_capacity_error_is',layout=1,mode=1)
        add('single_reduction_tile_no_ps',m=64,n=256,k=16,layout=3,requested_r=4,requested_w=16)
    if ia>=16:
        for mode,m,n in [(0,128,64),(1,64,128),(1,64,127)]:
            for layout in (0,2,3):
                add(f'ps715_r8_w4_mode{mode}_m{m}_n{n}_layout{layout}',m=m,n=n,k=33,
                    mode=mode,layout=layout,requested_r=8,requested_w=4,exact_reuse=True)
        add('s16_reservation_exceeded',m=128,n=64,k=16,layout=3,output16=True,
            requested_r=8,requested_w=4,error=1)
        add('after_s16_capacity_error',layout=3,output16=True)
    return result


def command(argv: list, log: Path, timeout=1200) -> int:
    log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('w') as stream:
        stream.write(' '.join(str(v) for v in argv)+'\n');stream.flush()
        try:
            return subprocess.run([str(v) for v in argv],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            return 124


def build(directory: Path, ia: int, args) -> Path:
    enable_is_mode=int(not getattr(args, 'ws_only', False))
    npu=ROOT/'rtl/npu'
    package=npu/'conv/conv_im2col_pkg.sv'
    packages=[package,npu/'conv/vector_engine_pkg.sv']
    sources=packages+[p for p in sorted(npu.rglob('*.sv')) if p not in packages]+sorted(npu.rglob('*.v'))
    sources += sorted((ROOT/'rtl/common').glob('regfile.v'))
    sources += [ROOT/'rtl/common/pseudo_dual_port_ram.v',ROOT/'rtl/axi_top/npu_axil_reg_if.sv',
                ROOT/'rtl/axi_top/npu_axil_top.sv',ROOT/'test/conv_npu/axi_memory.sv',HERE/'tb_matrix_layout.sv']
    sources += [Path(path) for path in getattr(args, 'extra_sources', [])]
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    binary=directory/'obj/Vtb_matrix_layout'
    manifest=directory/'build.json'
    if args.skip_build:
        previous=json.loads(manifest.read_text())
        if previous['source_sha256']!=hashes:
            raise RuntimeError('sources differ from existing simulator; rebuild required')
        if previous.get('enable_is_mode', 1)!=enable_is_mode:
            raise RuntimeError('compiled dataflow support differs')
        return binary
    argv=[args.verilator,'--binary','--timing','--assert','-sv','--top-module','tb_matrix_layout','-Wno-fatal',
          f'-I{npu/"ps_compact"}',f'-DTB_IA_CACHE_BLOCKS={ia}','-DTB_PS_STORAGE_ROWS=799','-DTB_S16_BANKS=4',
          f'-DTB_ENABLE_IS_MODE={enable_is_mode}',
          '--Mdir',directory/'obj','-j',args.jobs,'-CFLAGS','-std=c++20 -O1',
          '-MAKEFLAGS','OPT_FAST=-O1 OPT_SLOW=-O0',*sources]
    print(f'Building IA={ia}, PS=799, S16 banks=4',flush=True)
    code=command(argv,directory/'compile.log')
    after={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    manifest.write_text(json.dumps(dict(returncode=code,source_sha256=hashes,sources_unchanged_during_build=hashes==after,
                          enable_is_mode=enable_is_mode,
                          command=[str(v) for v in argv],binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest() if code==0 else None),indent=2)+'\n')
    if code or hashes!=after:
        raise RuntimeError((directory/'compile.log').read_text()[-6000:])
    return binary


def run(binary: Path,directory: Path,tasks: list[Path],random_wait: bool) -> dict:
    label='random_axi' if random_wait else 'fixed_axi'
    suite=directory/(label+'.suite')
    suite.write_text(''.join(f'{t}/config.mem {t}/init.mem {t}/golden.mem {t}/access.mem\n' for t in tasks))
    argv=[binary,f'+SUITE={suite}']+([] if random_wait else ['+NO_RANDOM_WAIT'])
    code=command(argv,directory/(label+'.log'),timeout=600)
    output=(directory/(label+'.log')).read_text()
    measurements=[{key:int(value) for key,value in re.findall(r'(\w+)=(\d+)',line)} for line in output.splitlines() if line.startswith('MATRIX_TASK_PASS')]
    for record in measurements:
        record['name']=tasks[record['task']].name
    passed=code==0 and f'MATRIX_LAYOUT_PASS tasks={len(tasks)}' in output and 'MATRIX_REGISTERS_PASS' in output
    result=dict(passed=passed,returncode=code,tasks=len(tasks),measurements=measurements,command=[str(v) for v in argv])
    print(label,'PASS' if passed else 'FAIL',f'{len(measurements)}/{len(tasks)}',flush=True)
    if not passed:
        print(output[-6500:],flush=True)
    return result


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'build/matrix_layout')
    parser.add_argument('--profiles',type=int,nargs='+',choices=[4,8,16],default=[8,4,16])
    parser.add_argument('--verilator',default='verilator')
    parser.add_argument('--jobs',type=int,default=2)
    parser.add_argument('--skip-build',action='store_true')
    parser.add_argument('--compact',action='store_true')
    parser.add_argument('--fixed-only',action='store_true')
    parser.add_argument('--ws-only',action='store_true',help='Build without IS hardware and select only WS workloads')
    parser.add_argument('--case',help='regular expression selecting case names')
    args=parser.parse_args();args.out=args.out.resolve();args.out.mkdir(parents=True,exist_ok=True)
    summary=dict(verilator=subprocess.check_output([args.verilator,'--version'],text=True).strip(),profiles=[])
    summary['generator_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    summary['tiling_helper_sha256']=hashlib.sha256((ROOT/'veri/top_regression/host_tiling.py').read_bytes()).hexdigest()
    passed=True
    for ia in args.profiles:
        directory=args.out/f'ia{ia}'
        directory.mkdir(parents=True,exist_ok=True)
        tasks=cases(directory/'cases',ia,args.compact or ia!=8)
        if args.ws_only:
            tasks=[t for t in tasks if json.loads((t/'case.json').read_text())['dataflow']=='WS']
        if args.case:
            tasks=[t for t in tasks if re.search(args.case,t.name)]
        if not tasks:
            raise RuntimeError('case selector matched no workloads')
        binary=build(directory,ia,args)
        runs=[run(binary,directory,tasks,False)]
        if runs[0]['passed'] and not args.fixed_only:
            runs.append(run(binary,directory,tasks,True))
        profile=dict(ia_cache_blocks=ia,ps_storage_rows=799,s16_fifo_banks=4,
                     enable_is_mode=int(not args.ws_only),runs=runs)
        summary['profiles'].append(profile)
        passed=passed and all(r['passed'] for r in runs)
        summary['passed']=passed
        (args.out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        if not passed:
            break
    print(args.out/'summary.json',flush=True)
    raise SystemExit(0 if passed else 1)


if __name__=='__main__':
    main()
