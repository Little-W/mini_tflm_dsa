// Task-cold operand retention, with 64-byte read allocation and 16-byte sectors.
// A: 256 KiB direct indexed. B: 32 KiB XOR indexed to avoid power-of-two
// column-stride conflicts. Raw INT8 bytes are retained before zero-point logic.
// External interface remains AXI32, with at most four ordered transactions.
module operand_read_cache #(
    parameter int AW=32, DW=32, OUTSTANDING=4,
    parameter int A_BYTES=262144, B_BYTES=32768
)(
    input logic clk, rst_n, flush,
    input logic prefetch_enable,
    input logic [AW-1:0] a_base, a_bytes, b_base, b_bytes,
    input logic s_arvalid, output logic s_arready,
    input logic [AW-1:0] s_araddr,
    input logic [7:0] s_arlen,
    input logic [2:0] s_arsize,
    input logic [1:0] s_arburst,
    output logic s_rvalid, input logic s_rready,
    output logic [DW-1:0] s_rdata,
    output logic [1:0] s_rresp, output logic s_rlast,
    output logic m_arvalid, input logic m_arready,
    output logic [AW-1:0] m_araddr,
    output logic [7:0] m_arlen,
    output logic [2:0] m_arsize,
    output logic [1:0] m_arburst,
    input logic m_rvalid, output logic m_rready,
    input logic [DW-1:0] m_rdata,
    input logic [1:0] m_rresp, input logic m_rlast,
    output logic idle
);
    localparam int AL=$clog2(A_BYTES), BL=$clog2(B_BYTES), BI=BL-4;
    localparam int QW=$clog2(OUTSTANDING), CW=$clog2(OUTSTANDING+1);
    (* ram_style="block" *) logic [31:0] a_ram[A_BYTES/4];
    (* ram_style="block" *) logic [31:0] b_ram[B_BYTES/4];
    (* ram_style="block" *) logic [AW-AL-1:0] a_tags[A_BYTES/16];
    (* ram_style="block" *) logic [AW-BL-1:0] b_tags[B_BYTES/16];
    localparam int AVDEPTH=A_BYTES/64, BVDEPTH=B_BYTES/64;
    localparam int APAGE=(AVDEPTH<256)?AVDEPTH:256, BPAGE=(BVDEPTH<256)?BVDEPTH:256;
    localparam int APW=$clog2(APAGE), BPW=$clog2(BPAGE);
    wire [AVDEPTH-1:0] a_valid_bank[4];
    wire [BVDEPTH-1:0] b_valid_bank[4];
    logic flush_pending;
    always_ff @(posedge clk) flush_pending <= !rst_n || flush;
    (* ram_style="registers" *) logic q_hit[OUTSTANDING], q_a[OUTSTANDING], q_b[OUTSTANDING], q_wide[OUTSTANDING];
    (* ram_style="registers" *) logic [AL-5:0] q_ai[OUTSTANDING][4];
    (* ram_style="registers" *) logic [BI-1:0] q_bi[OUTSTANDING][4];
    logic [AW-1:0] q_addr[OUTSTANDING], q_fetch[OUTSTANDING];
    logic [7:0] q_len[OUTSTANDING], q_first[OUTSTANDING];
    logic [QW-1:0] head, tail;
    logic [CW-1:0] count;
    logic [7:0] beat;
    logic hit_valid, fill_error;
    wire [31:0] hit_data;
    logic a_rd_en, b_rd_en, hit_read_a;
    logic [AL-3:0] a_rd_addr;
    logic [BL-3:0] b_rd_addr;
    logic [31:0] a_rd_data, b_rd_data;
    assign hit_data = hit_read_a ? a_rd_data : b_rd_data;
    logic [AW-1:0] a_base_q, a_end_q, b_base_q, b_end_q;
    logic prefetch_q;
    function automatic [BI-1:0] b_index(input logic [AW-1:0] offset);
        b_index=BI'((offset>>4) ^ ((offset>>BL)<<4));
    endfunction
    // Address decode, tag lookup, and request issue are separate stages.
    // One buffered request overlaps the four-entry in-flight response queue.
    typedef enum logic [1:0] {RQ_EMPTY, RQ_LOOKUP, RQ_COMPARE, RQ_ISSUE} request_state_t;
    request_state_t req_state;
    logic req_fast;
    logic [AW-1:0] req_addr, ar_a_offset, ar_b_offset;
    logic [7:0] req_len;
    logic [2:0] req_size;
    logic [1:0] req_burst;
    logic eligible_a, eligible_b, wide, hit_q;
    logic [AL-5:0] req_ai[4];
    logic [BI-1:0] req_bi[4];
    wire raw_aligned=s_araddr[3:0]==0 && s_arlen==3 && s_arsize==2 && s_arburst==1 && DW==32;
    wire raw_a=raw_aligned && s_araddr>=a_base_q && s_araddr+AW'(16)<=a_end_q;
    wire raw_b=raw_aligned && s_araddr>=b_base_q && s_araddr+AW'(16)<=b_end_q;
    wire [AW-1:0] raw_fetch64={s_araddr[AW-1:6],6'b0};
    wire raw_wide=prefetch_q && ((raw_a && raw_fetch64>=a_base_q && raw_fetch64+64<=a_end_q) ||
                  (raw_b && raw_fetch64>=b_base_q && raw_fetch64+64<=b_end_q));
    wire accept=s_arvalid && s_arready;
    logic fill_hazard;
    // A queued replacement may supersede a sector that an earlier fill has
    // just made valid. Stall matching lookups until all older fills retire.
    // This also merges duplicate in-flight requests into the completed line.
    always_comb begin
        fill_hazard=0;
        for(int i=0;i<OUTSTANDING;i++) begin
            automatic logic [QW-1:0] qi=head+QW'(i);
            if(i<int'(count) && !q_hit[qi]) begin
                for(int j=0;j<4;j++) begin
                    if(q_wide[qi] || j==0) begin
                        if(eligible_a && q_a[qi] && ar_a_offset[AL-1:4]==q_ai[qi][j]) fill_hazard=1;
                        if(eligible_b && q_b[qi] && b_index(ar_b_offset)==q_bi[qi][j]) fill_hazard=1;
                    end
                end
            end
        end
    end
    logic [AW-AL-1:0] a_tag_read;
    logic [AW-BL-1:0] b_tag_read;
    logic [AVDEPTH/APAGE-1:0] a_page_read[4];
    logic [BVDEPTH/BPAGE-1:0] b_page_read[4];
    logic commit_pending, commit_a, commit_b;
    logic [AL-5:0] commit_ai;
    logic [BI-1:0] commit_bi;
    wire commit_hazard=commit_pending && ((eligible_a && commit_a && ar_a_offset[AL-1:4]==commit_ai) ||
                       (eligible_b && commit_b && b_index(ar_b_offset)==commit_bi));
    wire lookup_read=req_state==RQ_LOOKUP && !fill_hazard && !commit_hazard;
    // With an empty response queue there is no pending replacement. Capture
    // the first tag read on AR acceptance and issue from its registered result.
    // A just-retired fill still takes the regular guarded lookup path.
    wire early_lookup=accept && req_state==RQ_EMPTY && count==0 && !commit_pending;
    wire lookup_capture=lookup_read || early_lookup;
    wire [AW-1:0] lookup_a_offset=early_lookup ? s_araddr-a_base_q : ar_a_offset;
    wire [AW-1:0] lookup_b_offset=early_lookup ? s_araddr-b_base_q : ar_b_offset;
    always_ff @(posedge clk) begin
        if(lookup_capture) begin
            a_tag_read<=a_tags[lookup_a_offset[AL-1:4]];
            b_tag_read<=b_tags[b_index(lookup_b_offset)];
        end
    end
    wire hit_a=eligible_a && a_page_read[ar_a_offset[5:4]][ar_a_offset[AL-1:6]>>APW] &&
               a_tag_read==ar_a_offset[AW-1:AL];
    wire hit_b=eligible_b && b_page_read[ar_b_offset[5:4]][(b_index(ar_b_offset)>>2)>>BPW] &&
               b_tag_read==ar_b_offset[AW-1:BL];
    wire hit=hit_a || hit_b;
    wire [AW-1:0] fetch64={req_addr[AW-1:6],6'b0};
    wire fast_issue=req_state==RQ_COMPARE && req_fast;
    wire issue_phase=req_state==RQ_ISSUE || fast_issue;
    wire issue_hit=fast_issue ? hit : hit_q;
    wire push=issue_phase && count<OUTSTANDING && (issue_hit || m_arready) && !flush && !flush_pending;
    wire [AW-1:0] fetch_addr=q_fetch[head]+(AW'(beat)<<2);
    wire [AW-1:0] fill_a=fetch_addr-a_base_q, fill_b=fetch_addr-b_base_q;
    wire requested=!q_wide[head] || (beat>=q_first[head] && beat<q_first[head]+4);
    wire pop=count!=0 && (q_hit[head] ? (s_rvalid && s_rready && s_rlast)
                                                    : (m_rvalid && m_rready && m_rlast));
    wire [QW-1:0] next_head=head+1'b1;
    wire [AW-1:0] next_a=q_addr[next_head]-a_base_q;
    wire [AW-1:0] next_b=q_addr[next_head]-b_base_q;
    wire [AW-1:0] a_offset=q_addr[head]-a_base_q;
    wire [AW-1:0] b_offset=q_addr[head]-b_base_q;
    wire [AW-1:0] hit_next_offset=AW'(beat+8'd1)<<2;

    assign m_arvalid=issue_phase && count<OUTSTANDING && !issue_hit && !flush && !flush_pending;
    // A requested sector can finish before the rest of its wide allocation.
    // Task retirement must wait for the physical RLAST and metadata commit;
    // flushing earlier would discard the owner of the remaining R beats.
    assign idle=rst_n && req_state==RQ_EMPTY && count==0 && !commit_pending &&
                !flush && !flush_pending && !s_arvalid;
    assign s_arready=(req_state==RQ_EMPTY || push) && !flush && !flush_pending && rst_n;
    assign m_araddr=wide ? fetch64 : req_addr;
    assign m_arlen=wide ? 8'd15 : req_len;
    assign m_arsize=req_size;
    assign m_arburst=req_burst;
    assign s_rvalid=(count!=0) && (q_hit[head] ? hit_valid : (m_rvalid && requested));
    assign s_rdata=q_hit[head] ? hit_data : m_rdata;
    assign s_rresp=q_hit[head] ? 2'b00 : m_rresp;
    assign s_rlast=q_hit[head] ? beat==q_len[head] :
                  (q_wide[head] ? beat==q_first[head]+3 : m_rlast);
    assign m_rready=count!=0 && !q_hit[head] && (!requested || s_rready);

    // Four sector banks give each validity page one invalidate port and one
    // completion port. A wide fill invalidates one sector in every bank.
    // Small reset pages avoid a packed 16K-bit vector with four variable writes.
    wire [AW-1:0] invalidate_a=(wide?fetch64:req_addr)-a_base_q;
    wire [AW-1:0] invalidate_b=(wide?fetch64:req_addr)-b_base_q;
    wire valid_fill=count!=0 && !q_hit[head] && m_rvalid && m_rready &&
                    beat[1:0]==3 && !fill_error && m_rresp==0;
    always_ff @(posedge clk) begin
        if(!rst_n || flush) commit_pending<=0;
        else commit_pending<=valid_fill;
        if(valid_fill) begin
            commit_a<=q_a[head]; commit_b<=q_b[head];
            commit_ai<=fill_a[AL-1:4]; commit_bi<=b_index(fill_b);
        end
    end
    for(genvar bank=0;bank<4;bank++) begin: g_valid_bank
        wire [1:0] a_distance=2'(bank)-invalidate_a[5:4];
        wire [1:0] b_distance=2'(bank)-invalidate_b[5:4];
        wire [AW-1:0] a_victim=invalidate_a+(AW'(a_distance)<<4);
        wire [AW-1:0] b_victim=invalidate_b+(AW'(b_distance)<<4);
        wire a_invalidate=push && !issue_hit && eligible_a && (wide || invalidate_a[5:4]==2'(bank));
        wire b_invalidate=push && !issue_hit && eligible_b && (wide || invalidate_b[5:4]==2'(bank));
        wire [AL-7:0] a_clear_index=a_victim[AL-1:6];
        wire [AL-7:0] a_fill_index=fill_a[AL-1:6];
        wire [BI-3:0] b_clear_index=b_index(b_victim)>>2;
        wire [BI-3:0] b_fill_index=b_index(fill_b)>>2;
        // A replacement is already recorded in the in-flight queue at push.
        // Its hazard check blocks matching lookups until the fill retires, so
        // physical valid-bit clearing may safely occur on the following edge.
        // This separates cache lookup from the wide valid-bit write decoder.
        logic [AL-7:0] a_clear_index_q, a_fill_index_q;
        logic [BI-3:0] b_clear_index_q, b_fill_index_q;
        always_ff @(posedge clk) begin
            a_clear_index_q <= a_clear_index;
            b_clear_index_q <= b_clear_index;
            a_fill_index_q <= a_fill_index;
            b_fill_index_q <= b_fill_index;
        end
        for(genvar page=0;page<AVDEPTH/APAGE;page++) begin:g_a_page
            (* DONT_TOUCH="TRUE" *) logic flush_local;
            logic [APAGE-1:0] valid;
            always_ff @(posedge clk) if(lookup_capture)
                a_page_read[bank][page]<=valid[lookup_a_offset[APW+5:6]];
            (* DONT_TOUCH="TRUE" *) logic invalidate_q, fill_q;
            always_ff @(posedge clk) begin
                if(!rst_n || flush) begin invalidate_q<=0; fill_q<=0; end
                else begin
                    invalidate_q<=a_invalidate && (int'(a_clear_index)>>APW)==page;
                    fill_q<=valid_fill && q_a[head] && fill_a[5:4]==2'(bank) && (int'(a_fill_index)>>APW)==page;
                end
            end
            always_ff @(posedge clk) flush_local <= !rst_n || flush;
            assign a_valid_bank[bank][page*APAGE+:APAGE]=valid;
            always_ff @(posedge clk) begin
                if(flush_local) valid<='0;
                else begin
                    if(invalidate_q) valid[a_clear_index_q[APW-1:0]]<=0;
                    if(fill_q) valid[a_fill_index_q[APW-1:0]]<=1;
                end
            end
        end
        for(genvar page=0;page<BVDEPTH/BPAGE;page++) begin:g_b_page
            (* DONT_TOUCH="TRUE" *) logic flush_local;
            logic [BPAGE-1:0] valid;
            always_ff @(posedge clk) if(lookup_capture)
                b_page_read[bank][page]<=valid[(b_index(lookup_b_offset)>>2)&(BPAGE-1)];
            (* DONT_TOUCH="TRUE" *) logic invalidate_q, fill_q;
            always_ff @(posedge clk) begin
                if(!rst_n || flush) begin invalidate_q<=0; fill_q<=0; end
                else begin
                    invalidate_q<=b_invalidate && (int'(b_clear_index)>>BPW)==page;
                    fill_q<=valid_fill && q_b[head] && fill_b[5:4]==2'(bank) && (int'(b_fill_index)>>BPW)==page;
                end
            end
            always_ff @(posedge clk) flush_local <= !rst_n || flush;
            assign b_valid_bank[bank][page*BPAGE+:BPAGE]=valid;
            always_ff @(posedge clk) begin
                if(flush_local) valid<='0;
                else begin
                    if(invalidate_q) valid[b_clear_index_q[BPW-1:0]]<=0;
                    if(fill_q) valid[b_fill_index_q[BPW-1:0]]<=1;
                end
            end
        end
    end

    // One explicit synchronous read port per payload RAM. Select the read
    // address before the RAM, preserving the original read-ahead edge exactly.
    // Multiple conditional array reads into one shared register prevent Vivado
    // from inferring block RAM for the large operand retention bank.
    always_comb begin
        a_rd_en = 0; b_rd_en = 0; a_rd_addr = 0; b_rd_addr = 0;
        if (pop && count > 1 && q_hit[next_head]) begin
            a_rd_en = q_a[next_head]; b_rd_en = !q_a[next_head];
            a_rd_addr = next_a[AL-1:2];
            b_rd_addr = {b_index(next_b), 2'b0};
        end else if (count != 0 && q_hit[head]) begin
            if (!hit_valid) begin
                a_rd_en = q_a[head]; b_rd_en = !q_a[head];
                a_rd_addr = a_offset[AL-1:2];
                b_rd_addr = {b_index(b_offset), 2'b0};
            end else if (s_rready && !s_rlast) begin
                a_rd_en = q_a[head]; b_rd_en = !q_a[head];
                a_rd_addr = (a_offset[AL-1:0] + hit_next_offset) >> 2;
                b_rd_addr = (int'(b_index(b_offset)) << 2) + int'(beat) + 1;
            end
        end
    end
    always_ff @(posedge clk) begin
        if (rst_n && !flush) begin
            if (a_rd_en) a_rd_data <= a_ram[a_rd_addr];
            if (b_rd_en) b_rd_data <= b_ram[b_rd_addr];
            if (a_rd_en || b_rd_en) hit_read_a <= a_rd_en;
            if (count != 0 && !q_hit[head] && m_rvalid && m_rready) begin
                if (q_a[head]) a_ram[fill_a[AL-1:2]] <= m_rdata;
                if (q_b[head]) b_ram[{b_index(fill_b),fill_b[3:2]}] <= m_rdata;
            end
        end
    end

    always_ff @(posedge clk) begin
        if(!rst_n || flush) begin
            req_state<=RQ_EMPTY;
            hit_q<=0;
            req_fast<=0;
        end else begin
            if(lookup_read) req_state<=RQ_COMPARE;
            if(req_state==RQ_COMPARE && !req_fast) begin
                hit_q<=hit;
                req_state<=RQ_ISSUE;
            end
            if(push) begin req_state<=RQ_EMPTY; req_fast<=0; end
            if(accept) begin
                req_state<=early_lookup ? RQ_COMPARE : RQ_LOOKUP;
                req_fast<=early_lookup;
                req_addr<=s_araddr; req_len<=s_arlen;
                req_size<=s_arsize; req_burst<=s_arburst;
                ar_a_offset<=s_araddr-a_base_q;
                ar_b_offset<=s_araddr-b_base_q;
                eligible_a<=raw_a; eligible_b<=raw_b; wide<=raw_wide;
                for(int j=0;j<4;j++) begin
                    req_ai[j]<=AL'( (raw_wide?raw_fetch64:s_araddr)-a_base_q+AW'(j*16))>>4;
                    req_bi[j]<=b_index((raw_wide?raw_fetch64:s_araddr)-b_base_q+AW'(j*16));
                end
            end
        end
    end

    always_ff @(posedge clk) begin
        if (!rst_n || flush) begin
            head<='0; tail<='0; count<='0; beat<='0;
            hit_valid<=0; fill_error<=0;
            a_base_q<=a_base; a_end_q<=a_base+a_bytes;
            b_base_q<=b_base; b_end_q<=b_base+b_bytes;
            prefetch_q<=prefetch_enable;
        end else begin
            case ({push,pop})
                2'b10: count<=count+1'b1;
                2'b01: count<=count-1'b1;
                default: ;
            endcase
            if (push) begin
                q_hit[tail]<=issue_hit; q_a[tail]<=eligible_a; q_b[tail]<=eligible_b;
                q_addr[tail]<=req_addr; q_len[tail]<=req_len;
                q_fetch[tail]<=wide ? fetch64 : req_addr;
                q_wide[tail]<=wide;
                q_first[tail]<=wide ? {4'b0,req_addr[5:2]} : 8'b0;
                for(int j=0;j<4;j++) begin
                    q_ai[tail][j]<=req_ai[j]; q_bi[tail][j]<=req_bi[j];
                end
                tail<=tail+1'b1;
            end
            if (count!=0 && q_hit[head]) begin
                if (!hit_valid) begin
                    hit_valid<=1;
                end
                if(s_rvalid && s_rready) beat<=beat+1'b1;
            end
            if(count!=0 && !q_hit[head] && m_rvalid && m_rready) begin
                beat<=beat+1'b1;
                if(m_rresp!=0) fill_error<=1;
                if(beat[1:0]==3 && !fill_error && m_rresp==0) begin
                    if(q_a[head]) begin
                        a_tags[fill_a[AL-1:4]]<=fill_a[AW-1:AL];
                    end
                    if(q_b[head]) begin
                        b_tags[b_index(fill_b)]<=fill_b[AW-1:BL];
                    end
                end
            end
            if(pop) begin
                head<=next_head; beat<='0; hit_valid<=0; fill_error<=0;
                // Read the next hit's first word on the retiring edge. This
                // avoids a fresh synchronous-RAM bubble at every 16-byte sector.
                if(count>1 && q_hit[next_head]) begin
                    hit_valid<=1;
                end
            end
        end
    end
`ifdef NPU_SIM_ASSERT
    initial assert(DW==32 && OUTSTANDING==4);
    always @(posedge clk) if(rst_n && !flush)
        assert(count<=OUTSTANDING) else $fatal(1,"operand cache queue overflow");
`endif
endmodule
