#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include "dsa_schedule.h"
#include "dsa_matrix.h"

int schedule_oracle(const uint32_t *words, size_t count, uint64_t *values)
{
    dsa_schedule_config_t c;
    dsa_schedule_t p;
    if (count*sizeof(*words)!=sizeof(c)) return -1;
    memcpy(&c,words,sizeof(c));
    if (!dsa_schedule_plan(&c,&p)) return 0;
    values[0]=p.dataflow_mode;
    values[1]=p.tiling.ia_reuse; values[2]=p.tiling.w_reuse;
    values[3]=p.tiling.row_groups; values[4]=p.tiling.row_tail_tiles;
    values[5]=p.tiling.col_groups; values[6]=p.tiling.col_tail_tiles;
    values[7]=p.candidates; values[8]=p.estimated_cycles;
    values[9]=p.read_words; values[10]=p.read_requests;
    values[11]=p.write_words; values[12]=p.write_requests;
    values[13]=p.compute_cycles; values[14]=p.ps_payload_bytes;
    values[15]=p.read_beats; values[16]=p.write_beats;
    return 1;
}

void operand_oracle(const uint32_t *words, size_t count, uint32_t rows,
    uint32_t width, uint32_t stride, uint32_t address, uint32_t merge,
    uint32_t packed, uint64_t *values)
{
    dsa_schedule_config_t c;
    if (count*sizeof(*words)!=sizeof(c)) {values[0]=values[1]=UINT64_MAX;return;}
    memcpy(&c,words,sizeof(c));
    dsa_schedule_operand(&c,rows,width,stride,address,merge,packed,&values[0],&values[1]);
}

int schedule_defaults(uint32_t *words, size_t count)
{
    dsa_schedule_config_t c;
    dsa_schedule_init(&c,17,31,65,16,8,16);
    if (count*sizeof(*words)!=sizeof(c)) return 0;
    memcpy(words,&c,sizeof(c));
    return 1;
}

uint64_t write_requests_oracle(const uint32_t *words, size_t count,
    uint32_t mode, uint32_t r, uint32_t w)
{
    dsa_schedule_config_t c;
    if (count*sizeof(*words)!=sizeof(c)) return UINT64_MAX;
    memcpy(&c,words,sizeof(c));
    return dsa_schedule_writes(&c,mode,r,w);
}

uint32_t packed_bytes_oracle(uint32_t rows,uint32_t depth,uint32_t width)
{
    return dsa_matrix_packed_bytes(rows,depth,width);
}

int pack_oracle(void *dst,uint32_t bytes,const void *src,
    uint32_t rows,uint32_t depth,uint32_t stride,uint32_t width)
{
    return dsa_matrix_pack(dst,bytes,src,rows,depth,stride,width);
}

int layout_oracle(const uint32_t *words,size_t count,uint32_t may_pack,uint64_t *values)
{
    dsa_schedule_config_t c;
    dsa_schedule_t p;
    uint32_t layout;
    if (count*sizeof(*words)!=sizeof(c)) return -1;
    memcpy(&c,words,sizeof(c));
    if (!dsa_schedule_plan_layout(&c,may_pack,&p,&layout)) return 0;
    values[0]=layout;values[1]=p.dataflow_mode;
    values[2]=p.tiling.ia_reuse;values[3]=p.tiling.w_reuse;
    values[4]=p.estimated_cycles;values[5]=p.read_words;values[6]=p.read_requests;
    values[7]=p.candidates;
    return 1;
}
