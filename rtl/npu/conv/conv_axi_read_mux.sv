// SPDX-License-Identifier: Apache-2.0
// Shared, ordered AXI read port. GEMM retains its original pipelined path.
// Conv arbitrates one burst at a time between the legacy DMA and input cache.
// Holding the grant before ARREADY guarantees stable AR payload under stalls.
module conv_axi_read_mux #( // 共享两个请求来源的 AXI 读取端口，按突发保存响应归属及等待期间的地址。
    parameter int ADDR_W=32,
    parameter int DATA_W=32
) (
    input logic clk /* 模块工作时钟。 */, rst_n /* 低有效复位输入。 */, enable /* 启用两路按突发仲裁，关闭时直通 A 路。 */,
    input logic a_arvalid /* A 路 DMA 的 AXI 接口：读地址请求有效。 */, output logic a_arready /* A 路 DMA 的 AXI 接口：能够接收读地址请求。 */,
    input logic [ADDR_W-1:0] a_araddr, // A 路 DMA 的 AXI 接口：读事务起始字节地址。
    input logic [7:0] a_arlen, // A 路 DMA 的 AXI 接口：读突发的传输拍数减一。
    input logic [2:0] a_arsize, // A 路 DMA 的 AXI 接口：每拍读取字节数的二进制对数。
    input logic [1:0] a_arburst, // A 路 DMA 的 AXI 接口：读事务的突发类型。
    output logic a_rvalid /* A 路 DMA 的 AXI 接口：返回的读取数据有效。 */, input logic a_rready /* A 路 DMA 的 AXI 接口：能够接收读取响应。 */,
    output logic [DATA_W-1:0] a_rdata, // A 路 DMA 的 AXI 接口：读取响应的数据。
    output logic [1:0] a_rresp /* A 路 DMA 的 AXI 接口：读取响应的状态编码。 */, output logic a_rlast /* A 路 DMA 的 AXI 接口：当前读突发的最后一拍。 */,
    input logic b_arvalid /* B 路输入缓存的 AXI 接口：读地址请求有效。 */, output logic b_arready /* B 路输入缓存的 AXI 接口：能够接收读地址请求。 */,
    input logic [ADDR_W-1:0] b_araddr, // B 路输入缓存的 AXI 接口：读事务起始字节地址。
    input logic [7:0] b_arlen, // B 路输入缓存的 AXI 接口：读突发的传输拍数减一。
    input logic [2:0] b_arsize, // B 路输入缓存的 AXI 接口：每拍读取字节数的二进制对数。
    input logic [1:0] b_arburst, // B 路输入缓存的 AXI 接口：读事务的突发类型。
    output logic b_rvalid /* B 路输入缓存的 AXI 接口：返回的读取数据有效。 */, input logic b_rready /* B 路输入缓存的 AXI 接口：能够接收读取响应。 */,
    output logic [DATA_W-1:0] b_rdata, // B 路输入缓存的 AXI 接口：读取响应的数据。
    output logic [1:0] b_rresp /* B 路输入缓存的 AXI 接口：读取响应的状态编码。 */, output logic b_rlast /* B 路输入缓存的 AXI 接口：当前读突发的最后一拍。 */,
    output logic m_arvalid /* 外部 AXI 接口：读地址请求有效。 */, input logic m_arready /* 外部 AXI 接口：能够接收读地址请求。 */,
    output logic [ADDR_W-1:0] m_araddr, // 外部 AXI 接口：读事务起始字节地址。
    output logic [7:0] m_arlen, // 外部 AXI 接口：读突发的传输拍数减一。
    output logic [2:0] m_arsize, // 外部 AXI 接口：每拍读取字节数的二进制对数。
    output logic [1:0] m_arburst, // 外部 AXI 接口：读事务的突发类型。
    input logic m_rvalid /* 外部 AXI 接口：返回的读取数据有效。 */, output logic m_rready /* 外部 AXI 接口：能够接收读取响应。 */,
    input logic [DATA_W-1:0] m_rdata, // 外部 AXI 接口：读取响应的数据。
    input logic [1:0] m_rresp /* 外部 AXI 接口：读取响应的状态编码。 */, input logic m_rlast /* 外部 AXI 接口：当前读突发的最后一拍。 */,
    output logic idle // 当前没有在途突发或等待接收的已选地址。
);
    logic active, owner, hold_grant, held_owner, prefer_b;
    logic select_b, retire, address_slot;
    assign retire = active && m_rvalid && (owner ? b_rready : a_rready) && m_rlast;
    assign address_slot = !active || retire;
    assign select_b = hold_grant ? held_owner :
                      (b_arvalid && (!a_arvalid || prefer_b));
    // Clients report their pending work separately. This status describes the
    // transactions and stalled address grants retained inside the arbiter.
    assign idle = !active && !hold_grant;
    // 当前模式和响应来源决定返回通道，保持直通模式的就绪传播。
    assign m_rready = !enable ? a_rready : active && (owner ? b_rready : a_rready);
    always_comb begin
        a_arready = 1'b0; b_arready = 1'b0;
        a_rvalid = 1'b0; b_rvalid = 1'b0;
        a_rdata = m_rdata; b_rdata = m_rdata;
        a_rresp = m_rresp; b_rresp = m_rresp;
        a_rlast = m_rlast; b_rlast = m_rlast;
        m_arvalid = a_arvalid; m_araddr = a_araddr;
        m_arlen = a_arlen; m_arsize = a_arsize; m_arburst = a_arburst;
        if (!enable) begin
            a_arready = m_arready;
            a_rvalid = m_rvalid;
        end else begin
            m_arvalid = address_slot && (select_b ? b_arvalid : a_arvalid);
            m_araddr = select_b ? b_araddr : a_araddr;
            m_arlen = select_b ? b_arlen : a_arlen;
            m_arsize = select_b ? b_arsize : a_arsize;
            m_arburst = select_b ? b_arburst : a_arburst;
            a_arready = address_slot && !select_b && m_arready;
            b_arready = address_slot && select_b && m_arready;
            a_rvalid = active && !owner && m_rvalid;
            b_rvalid = active && owner && m_rvalid;
        end
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            active <= 1'b0; owner <= 1'b0;
            hold_grant <= 1'b0; held_owner <= 1'b0; prefer_b <= 1'b0;
        end else if (!enable) begin
            active <= 1'b0; hold_grant <= 1'b0; prefer_b <= 1'b0;
        end else begin
            if (retire) active <= 1'b0;
            if (address_slot && m_arvalid) begin
                if (m_arready) begin
                    active <= 1'b1; owner <= select_b;
                    hold_grant <= 1'b0; prefer_b <= !select_b;
                end else begin
                    hold_grant <= 1'b1; held_owner <= select_b;
                end
            end
        end
    end

`ifdef NPU_SIM_ASSERT
    initial begin : check_m_arvalid_stability
        logic stalled;
        logic [$bits({m_araddr,m_arlen,m_arsize,m_arburst})-1:0] held_payload;
        stalled=1'b0;
        forever begin
            @(posedge clk);
            if (!rst_n) stalled=1'b0;
            else begin
                if (stalled) assert(m_arvalid && {m_araddr,m_arlen,m_arsize,m_arburst}==held_payload);
                stalled=m_arvalid && !m_arready;
                held_payload={m_araddr,m_arlen,m_arsize,m_arburst};
            end
        end
    end
`endif
endmodule
