"""Executable specification, NOT an RTL simulator.

Independent paths:
  * counted_tiles: counter-based hardware-style im2col + read-only cache;
  * direct_im2col: direct coordinate equations, no cache;
  * tests/direct_conv.c: separately compiled direct Conv oracle.
All transactions cover only the configured input interval.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from collections import Counter
from typing import Iterator
import random


@dataclass(frozen=True)
class Config:
    h: int; w: int; cin: int
    kh: int; kw: int; oh: int; ow: int
    sh: int = 1; sw: int = 1
    dh: int = 1; dw: int = 1
    pt: int = 0; pl: int = 0
    gc: int = 0; go: int = 0
    offset: int = 0; s16: bool = False
    base: int = 0x1000

    @property
    def group_c(self) -> int: return self.gc or self.cin
    @property
    def bpe(self) -> int: return 2 if self.s16 else 1
    @property
    def nbytes(self) -> int: return self.h*self.w*self.cin*self.bpe
    @property
    def red(self) -> int: return self.kh*self.kw*self.group_c
    @property
    def positions(self) -> int: return self.oh*self.ow

    def validate(self) -> None:
        dims = [self.h,self.w,self.cin,self.kh,self.kw,self.oh,self.ow,
                self.sh,self.sw,self.dh,self.dw,self.group_c]
        if any(type(v) is not int or not 1 <= v <= 65535 for v in dims):
            raise ValueError("positive u16 dimensions required")
        if not 0 <= self.go <= 65535 or self.go+self.group_c > self.cin:
            raise ValueError("group range exceeds input channels")
        if not 0 <= self.pt <= 65535 or not 0 <= self.pl <= 65535:
            raise ValueError("padding is a nonnegative u16")
        if not 0 <= self.base < 2**32 or self.base+self.nbytes >= 2**32:
            raise ValueError("input address interval overflows")
        if self.red > 2**32-1:
            raise ValueError("reduction length overflow")
        if self.s16:
            if self.offset != 0 or self.base & 1:
                raise ValueError("s16 requires zero offset and aligned base")
        elif not -127 <= self.offset <= 128:
            raise ValueError("s8 offset is the additive negative zero point")


def udiv32(a: int, b: int) -> tuple[int,int]:
    if not 0 <= a < 2**32 or not 1 <= b < 2**32:
        raise ValueError("udiv32 operands out of range")
    rem=0; q=0
    for bit in range(31,-1,-1):
        rem=(rem<<1)|((a>>bit)&1)
        q <<= 1
        if rem>=b: rem-=b; q|=1
    return q,rem


@dataclass(frozen=True)
class Burst:
    addr: int; size: int; beats: int
    @property
    def nbytes(self) -> int: return (1<<self.size)*self.beats


def span_bursts(start: int, count: int) -> Iterator[Burst]:
    """Same transaction policy as conv_axi_span_reader, independent Python code."""
    if not 0 < count <= 65535 or start < 0 or start+count >= 2**32:
        raise ValueError("invalid span")
    while count:
        if start & 3 or count<4:
            b=Burst(start,0,1)
        else:
            n=min(count//4,256,(4096-(start&4095))//4)
            b=Burst(start,2,n)
        assert (b.addr&4095)+b.nbytes<=4096
        yield b
        start+=b.nbytes; count-=b.nbytes


class BusFault(RuntimeError): pass


class Memory:
    def __init__(self, cfg: Config, values: list[int]):
        cfg.validate()
        if len(values)!=cfg.h*cfg.w*cfg.cin: raise ValueError("input length mismatch")
        lo,hi=(-32768,32767) if cfg.s16 else (-128,127)
        if any(not lo<=v<=hi for v in values): raise ValueError("input range")
        self.base=cfg.base
        self.data=b''.join(int(v).to_bytes(cfg.bpe,'little',signed=True) for v in values)
        self.end=self.base+len(self.data)
        self.read_bytes=0; self.bursts=[]; self.address_reads=Counter()
        self.fail_next=False

    def fetch(self, start: int, count: int) -> bytes:
        if not self.base<=start<start+count<=self.end:
            raise AssertionError(f"out of range transaction {start:#x}+{count}")
        buf=bytearray()
        failure=self.fail_next; self.fail_next=False
        # Drain the complete span even if an AXI RRESP error is injected.
        for b in span_bursts(start,count):
            self.bursts.append(b)
            for i in range(b.nbytes): self.address_reads[b.addr+i]+=1
            self.read_bytes+=b.nbytes
            buf.extend(self.data[b.addr-self.base:b.addr-self.base+b.nbytes])
        if failure: raise BusFault("injected read response error")
        return bytes(buf)


@dataclass
class Line:
    tag: int = -1
    valid: bool = False
    data: bytearray | None = None


class ReadCache:
    def __init__(self, mem: Memory, capacity: int=4096, ways: int=2, line_bytes: int=16, hash_index: bool=False):
        self.ways=ways; self.lb=line_bytes; self.hash_index=hash_index
        if ways not in (1,2): raise ValueError("implemented ways: 1 or 2")
        self.sets=capacity//(ways*line_bytes)
        if capacity!=self.sets*ways*line_bytes or self.sets<2 or self.sets&(self.sets-1):
            raise ValueError("power-of-two set count >=2 required")
        if line_bytes<8 or line_bytes>256 or line_bytes&(line_bytes-1):
            raise ValueError("line size")
        self.lines=[[Line(data=bytearray(line_bytes)) for _ in range(ways)]
                    for _ in range(self.sets)]
        self.lru=[0]*self.sets
        self.configure(mem)

    def configure(self,mem: Memory) -> None:
        self.mem=mem; self.hits=0; self.misses=0
        for row in self.lines:
            for l in row: l.valid=False
        self.lru[:]=[0]*self.sets

    def read_word(self, addr: int) -> bytes:
        if not self.mem.base<=addr<self.mem.end: raise ValueError("demand out of bounds")
        block=addr//self.lb; tag=block//self.sets
        idx=(block ^ (tag if self.hash_index else 0)) & (self.sets-1)
        row=self.lines[idx]
        way=next((w for w,l in enumerate(row) if l.valid and l.tag==tag),None)
        if way is not None:
            self.hits+=1
        else:
            self.misses+=1
            way=next((w for w,l in enumerate(row) if not l.valid),self.lru[idx])
            line=row[way]; line.valid=False
            begin=block*self.lb
            lo=max(begin,self.mem.base); hi=min(begin+self.lb,self.mem.end)
            data=self.mem.fetch(lo,hi-lo)  # exception leaves the destination invalid
            line.data[lo-begin:hi-begin]=data
            line.tag=tag; line.valid=True
        self.lru[idx]=1-way if self.ways==2 else 0
        off=(addr&~3)%self.lb
        return bytes(row[way].data[off:off+4])


class NoCache:
    """Baseline: only the same one-word holding register used by counted_tiles."""
    def __init__(self,mem:Memory): self.mem=mem; self.hits=0; self.misses=0
    def read_word(self,addr:int)->bytes:
        self.misses+=1
        begin=addr&~3; lo=max(begin,self.mem.base); hi=min(begin+4,self.mem.end)
        word=bytearray(4)
        word[lo-begin:hi-begin]=self.mem.fetch(lo,hi-lo)
        return bytes(word)


@dataclass(frozen=True)
class Tile:
    p0: int; q0: int; rows: int; slot: int = 0


def tile_plan(cfg:Config,size:int=16,reuse_rows:int=2,replays:int=1)->list[Tile]:
    """Synthetic reduction-major tile schedule; NOT a trace from upstream RTL.

    Cache correctness does not depend on this order. 'replays' models repeated
    activation requests for output-channel groups; actual IA reuse may remove them.
    """
    nt=(cfg.positions+size-1)//size
    ans=[]
    for rg in range(0,nt,reuse_rows):
        for _ in range(replays):
            for q0 in range(0,cfg.red,size):
                for rt in range(rg,min(rg+reuse_rows,nt)):
                    ans.append(Tile(rt*size,q0,min(size,cfg.positions-rt*size),rt%(2*reuse_rows)))
    return ans


def counted_tiles(cfg:Config, cache:ReadCache|NoCache, plan:list[Tile], size:int=16,
                  lanes:int=2)->Iterator[tuple[Tile,list[list[int]],list[tuple]]]:
    """Counter-style frontend. A one-word hold register survives tile boundaries."""
    cfg.validate()
    hold_addr=None; hold_word=b''
    for t in plan:
        if not 0<t.rows<=size or t.p0+t.rows>cfg.positions or not 0<=t.q0<cfg.red:
            raise ValueError("tile outside logical matrix")
        oy,ox=udiv32(t.p0,cfg.ow)
        tap0,ch0=udiv32(t.q0,cfg.group_c)
        ky0,kx0=udiv32(tap0,cfg.kw)
        result=[]; writes=[]
        for row in range(t.rows):
            ky,kx,ch=ky0,kx0,ch0; col=0; q=t.q0; vals=[]
            while col<size:
                iy=oy*cfg.sh-cfg.pt+ky*cfg.dh
                ix=ox*cfg.sw-cfg.pl+kx*cfg.dw
                pad=q>=cfg.red or not(0<=iy<cfg.h and 0<=ix<cfg.w)
                n=min(lanes,size-col)
                if q<cfg.red: n=min(n,cfg.group_c-ch,cfg.red-q)
                address=None
                if pad:
                    vv=[0]*n
                else:
                    address=cfg.base+((iy*cfg.w+ix)*cfg.cin+cfg.go+ch)*cfg.bpe
                    n=min(n,(4-(address&3))//cfg.bpe)
                    wa=address&~3
                    if hold_addr!=wa:
                        hold_word=cache.read_word(address); hold_addr=wa
                    start=address&3
                    vv=[int.from_bytes(hold_word[start+j*cfg.bpe:start+(j+1)*cfg.bpe],
                                       'little',signed=True)+cfg.offset for j in range(n)]
                assert n>0
                vals.extend(vv)
                writes.append((row,col,tuple(vv),address))
                col+=n; q+=n
                if q<cfg.red:
                    ch+=n
                    if ch==cfg.group_c:
                        ch=0; kx+=1
                        if kx==cfg.kw: kx=0; ky+=1
            result.append(vals)
            ox+=1
            if ox==cfg.ow: ox=0; oy+=1
        yield t,result,writes


def direct_im2col(cfg:Config, values:list[int], t:Tile, size:int)->list[list[int]]:
    out=[]
    for p in range(t.p0,t.p0+t.rows):
        oy,ox=divmod(p,cfg.ow)
        expanded=[]
        for ky in range(cfg.kh):
            for kx in range(cfg.kw):
                iy=oy*cfg.sh-cfg.pt+ky*cfg.dh; ix=ox*cfg.sw-cfg.pl+kx*cfg.dw
                for ch in range(cfg.group_c):
                    v=0
                    if 0<=iy<cfg.h and 0<=ix<cfg.w:
                        v=values[(iy*cfg.w+ix)*cfg.cin+cfg.go+ch]+cfg.offset
                    expanded.append(v)
        out.append((expanded[t.q0:t.q0+size]+[0]*size)[:size])
    return out


def reconstruct_matrix(cfg:Config, results:list, size:int)->list[list[int]]:
    matrix=[[None]*cfg.red for _ in range(cfg.positions)]
    for t,values,_ in results:
        for r,row in enumerate(values):
            for j,val in enumerate(row):
                if t.q0+j<cfg.red:
                    prev=matrix[t.p0+r][t.q0+j]
                    assert prev is None or prev==val
                    matrix[t.p0+r][t.q0+j]=val
    if any(v is None for row in matrix for v in row): raise AssertionError("missing matrix element")
    return matrix


def i32(x:int)->int: return ((x+2**31)%2**32)-2**31


def matmul_conv(matrix:list[list[int]],weights:list[int],bias:list[int],cout:int)->list[int]:
    k=len(matrix[0]); out=[]
    for row in matrix:
        for oc in range(cout):
            out.append(i32(bias[oc]+sum(a*b for a,b in zip(row,weights[oc*k:(oc+1)*k]))))
    return out


def requantize_two_round(value:int,multiplier:int,shift:int,offset:int,amin:int,amax:int)->int:
    """Explicit numerical contract. Not claimed to reproduce uninspected NPU RTL.
    Assumes the pre-multiply left shift fits signed 32 bits. Uses rounded high
    multiply without saturation followed by divide-by-power-of-two ties away.
    """
    v=value*(1<<max(shift,0))
    if not -2**31<=v<2**31: raise OverflowError("left shift overflow")
    v=(v*multiplier+(1<<30))>>31
    r=max(-shift,0)
    if r:
        mask=(1<<r)-1; remainder=v&mask; threshold=(mask>>1)+(1 if v<0 else 0)
        v=(v>>r)+(1 if remainder>threshold else 0)
    return max(amin,min(amax,v+offset))


def handshake_span(start:int,count:int,rng:random.Random)->dict:
    """Protocol-level transaction model with held AR/R payloads under stalls.
    This checks the policy/model, not SystemVerilog event semantics.
    """
    cycles=0; received=[]; ar_stalls=0; r_stalls=0
    for b in span_bursts(start,count):
        saved=(b.addr,b.size,b.beats)
        while True:
            cycles+=1
            if rng.random()<0.63: break
            ar_stalls+=1
            assert saved==(b.addr,b.size,b.beats)
        for beat in range(b.beats):
            while rng.random()<0.25: cycles+=1
            addr=b.addr+beat*(1<<b.size)
            payload=(addr,b.size,beat==b.beats-1)
            while True:
                cycles+=1
                if rng.random()<0.71: break
                r_stalls+=1
                assert payload==(addr,b.size,beat==b.beats-1)
            received.extend(range(addr,addr+(1<<b.size)))
    assert received==list(range(start,start+count))
    return dict(cycles=cycles,ar_stalls=ar_stalls,r_stalls=r_stalls)
