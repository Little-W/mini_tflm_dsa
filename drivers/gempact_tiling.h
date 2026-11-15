#ifndef GEMPACT_TILING_H
#define GEMPACT_TILING_H
#include <stdint.h>
/* Host/compiler helper. rows/cols refer to the public logical output shape. */
typedef struct {
    uint32_t ia_reuse, w_reuse;
    uint32_t row_groups, row_tail_tiles, col_groups, col_tail_tiles;
} gempact_tiling_t;

#ifndef DSA_PCR_ENGINE
#define DSA_PCR_ENGINE 0
#endif
#if DSA_PCR_ENGINE
#if !defined(DSA_PANEL_MAX_R) || !defined(DSA_PANEL_MAX_W) || !defined(DSA_PS_POOL_BYTES)
#error "PCR firmware requires the configured panel limits and PS pool size"
#endif
#ifndef DSA_PS_FORCE_RAW
#define DSA_PS_FORCE_RAW 0
#endif
#endif

static inline uint32_t gempact_ceil_div(uint32_t a, uint32_t b) {
    return a/b + (a%b != 0u);
}

/* PCR K64 panels admit arbitrary integer groups, not just powers of two.
 * The direction remains the caller's WS/IS direction. Requests are upper
 * bounds (zero means automatic); the selected group always fits the physical
 * panel limits and the configured PS pool. Compact planning uses the same
 * nominal three-page rule as scripts/capacity. It preserves INT32 values;
 * dynamic completion in RTL still handles records which grow beyond S24.
 */
static inline int gempact_plan_panel(uint32_t rows, uint32_t cols,
    uint32_t max_r, uint32_t max_w, uint32_t pool_bytes,
    uint32_t req_r, uint32_t req_w, int is_mode, int force_raw,
    gempact_tiling_t *out, uint64_t *payload_bound) {
    uint32_t tr, tc, rcap, wcap, pages;
    uint64_t best_key[8] = {0};
    uint32_t best_pages = 0;
    gempact_tiling_t best = {0};
    int found = 0;
    if (!out || !rows || !cols || ((rows|cols)&15u) ||
        rows >= (1u<<20) || cols >= (1u<<20) ||
        !max_r || max_r>32u || !max_w || max_w>32u ||
        pool_bytes<1024u || pool_bytes%256u || pool_bytes/256u>4095u)
        return 0;
    tr = (is_mode ? cols : rows)/16u;
    tc = (is_mode ? rows : cols)/16u;
    pages = pool_bytes/256u;
    rcap = tr<max_r ? tr:max_r;
    wcap = tc<max_w ? tc:max_w;
    if (req_r && req_r<rcap) rcap=req_r;
    if (req_w && req_w<wcap) wcap=req_w;
    for (uint32_t r=1; r<=rcap; ++r) {
        for (uint32_t w=1; w<=wcap; ++w) {
            uint32_t needed = force_raw ? 4u*r*w : 3u*r*w+r;
            uint32_t initial = r*w+3u*r;
            uint32_t rg, cg, rt, ct;
            uint64_t groups, bursts=0, key[8];
            int better=0;
            if (!force_raw && initial>needed) needed=initial;
            if (needed>pages) continue;
            rg=gempact_ceil_div(tr,r); cg=gempact_ceil_div(tc,w);
            rt=tr-(rg-1u)*r; ct=tc-(cg-1u)*w;
            if (rg>65535u || cg>65535u) continue;
            groups=(uint64_t)rg*cg;
            /* Full/tail classes avoid a loop over all output groups.
             * AW is an address-neutral estimate for compact row-major INT8 C.
             * Actual AXI address boundaries can add transactions. */
            for (uint32_t ri=0;ri<2u;++ri) {
                uint32_t ar=ri ? rt:r, nr=ri ? 1u:rg-1u;
                for (uint32_t wi=0;wi<2u;++wi) {
                    uint32_t aw=wi ? ct:w, nw=wi ? 1u:cg-1u;
                    uint32_t width=16u*(is_mode ? ar:aw);
                    uint32_t height=16u*(is_mode ? aw:ar);
                    uint32_t per_group = width==cols ?
                        gempact_ceil_div(width*height,1024u) :
                        height*gempact_ceil_div(width,1024u);
                    bursts+=(uint64_t)nr*nw*per_group;
                }
            }
            /* K and tile size multiply every read/frame score equally. */
            key[0]=(uint64_t)tr*cg+(uint64_t)tc*rg;
            key[1]=bursts;
            key[2]=(uint64_t)tc*rg;
            key[3]=groups;
            key[4]=groups*r*w-(uint64_t)tr*tc;
            key[5]=1024u-r*w;
            key[6]=32u-r;
            key[7]=32u-w;
            for (uint32_t i=0;i<8u;++i) {
                if (!found || key[i]<best_key[i]) {better=1;break;}
                if (key[i]>best_key[i]) break;
            }
            if (better) {
                for (uint32_t i=0;i<8u;++i) best_key[i]=key[i];
                best.ia_reuse=r; best.w_reuse=w;
                best.row_groups=rg; best.row_tail_tiles=rt;
                best.col_groups=cg; best.col_tail_tiles=ct;
                best_pages=needed; found=1;
            }
        }
    }
    if (!found) return 0;
    *out=best;
    if (payload_bound) *payload_bound=(uint64_t)best_pages*256u;
    return 1;
}

static inline uint32_t gempact_floor_supported(uint32_t x) {
    uint32_t p=1;
    if (x==25) return 25;
    while (p <= x/2u) p <<= 1;
    return p;
}
static inline int gempact_plan_tiling(uint32_t rows, uint32_t cols,
    uint32_t size, uint32_t cache, uint32_t ps, uint32_t req_r, uint32_t req_w,
    int is_mode, int per_channel, gempact_tiling_t *out) {
    uint32_t tr,tc,rc,wc,wr,r,w,tmp;
    if (!out || !rows || !cols || !size || (size & (size-1u)) || !cache || !ps) return 0;
    if (is_mode) {tmp=rows;rows=cols;cols=tmp;}
    tr=rows/size+(rows%size!=0u);tc=cols/size+(cols%size!=0u);
    tmp=cache/2u;if (!tmp) tmp=1;
    rc=gempact_floor_supported(tr<tmp?tr:tmp);
    wr=tc<ps?tc:ps;wc=gempact_floor_supported(wr);
    r=gempact_floor_supported(!req_r||req_r>=rc?rc:req_r);
    w=gempact_floor_supported(!req_w||req_w>=wc?wc:req_w);
    if (is_mode && per_channel && r>wc) r=wc;
    if (is_mode && w<r && wr>=r) w=r;
    out->ia_reuse=r;out->w_reuse=w;
    out->row_groups=tr/r+(tr%r!=0u);out->row_tail_tiles=tr%r?tr%r:r;
    out->col_groups=tc/w+(tc%w!=0u);out->col_tail_tiles=tc%w?tc%w:w;
    return out->row_groups<=65535u && out->col_groups<=65535u && r<=65535u && w<=65535u;
}

/* Logical sector-pool admission, host only. pool_bytes=0 selects the legacy
 * uncompressed profile. For the current fixed 16-lane codec every record may
 * require 64 B. Include the spare frame used while reading the old frame and
 * writing the new frame; do not budget from an average compression ratio.
 * The independent mode directory is NOT deducted from the payload pool twice.
 */
static inline uint64_t gempact_ps_payload_bound(uint32_t size, uint32_t r,
                                               uint32_t w) {
    return (((uint64_t)r+1u)*size-1u)*((uint64_t)w+1u)*size*4u;
}
static inline int gempact_supported_reuse(uint32_t x) {
    return x && ((x & (x-1u))==0u || x==25u);
}
static inline int gempact_plan_capacity(uint32_t rows, uint32_t cols,
    uint32_t size, uint32_t cache, uint32_t ps, uint32_t req_r, uint32_t req_w,
    int is_mode, int per_channel, uint32_t pool_bytes,
    gempact_tiling_t *out, uint64_t *payload_bound) {
#if DSA_PCR_ENGINE
    (void)cache; (void)ps;
    if (size!=16u || per_channel || pool_bytes!=DSA_PS_POOL_BYTES) return 0;
    return gempact_plan_panel(rows,cols,DSA_PANEL_MAX_R,DSA_PANEL_MAX_W,
        pool_bytes,req_r,req_w,is_mode,DSA_PS_FORCE_RAW,out,payload_bound);
#else
    gempact_tiling_t cap, candidate, best;
    uint64_t best_cost=UINT64_MAX, best_area=0, best_bytes=UINT64_MAX;
    uint32_t tr,tc,sr,sc,r,w; int found=0;
    if (!out || !gempact_plan_tiling(rows,cols,size,cache,ps,req_r,req_w,
                                     is_mode,per_channel,&cap)) return 0;
    if (!pool_bytes) {
        *out=cap; if(payload_bound) *payload_bound=0; return 1;
    }
    /* The sector codec is a fixed 16xINT32 record, unlike the legacy RAM. */
    if (size!=16u || pool_bytes%64u) return 0;
    if (gempact_ps_payload_bound(size,cap.ia_reuse,cap.w_reuse)<=pool_bytes) {
        *out=cap;
        if(payload_bound) *payload_bound=gempact_ps_payload_bound(size,cap.ia_reuse,cap.w_reuse);
        return 1;
    }
    sr=is_mode?cols:rows; sc=is_mode?rows:cols;
    tr=sr/size+(sr%size!=0u); tc=sc/size+(sc%size!=0u);
    /* At most 16 powers of two and the special factor 25 are evaluated. */
    for (uint32_t ri=0;ri<17u;ri++) {
        r=ri==16u?25u:(1u<<ri);
        if (r>cap.ia_reuse) continue;
        for (uint32_t wi=0;wi<17u;wi++) {
            uint64_t bytes,cost,area;
            w=wi==16u?25u:(1u<<wi);
            if (w>cap.w_reuse) continue;
            if (!gempact_plan_tiling(rows,cols,size,cache,ps,r,w,is_mode,
                                     per_channel,&candidate)) continue;
            /* IS legality can increase W; evaluate the actual pair only. */
            if (candidate.ia_reuse!=r || candidate.w_reuse!=w) continue;
            bytes=gempact_ps_payload_bound(size,r,w);
            if (bytes>pool_bytes) continue;
            cost=(uint64_t)sr*(tc/w+(tc%w!=0u))+
                 (uint64_t)sc*(tr/r+(tr%r!=0u));
            area=(uint64_t)r*w;
            if (!found || cost<best_cost || (cost==best_cost &&
                (area>best_area || (area==best_area && bytes<best_bytes)))) {
                found=1; best=candidate;best_cost=cost;best_area=area;best_bytes=bytes;
            }
        }
    }
    if (!found) return 0;
    *out=best;if(payload_bound) *payload_bound=best_bytes;return 1;
#endif
}
#endif
