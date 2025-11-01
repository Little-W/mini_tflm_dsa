// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Tracing implementation internals
#include "verilated_vcd_c.h"
#include "Vtb_e203_nice__Syms.h"


void Vtb_e203_nice___024root__trace_chg_0_sub_0(Vtb_e203_nice___024root* vlSelf, VerilatedVcd::Buffer* bufp);

void Vtb_e203_nice___024root__trace_chg_0(void* voidSelf, VerilatedVcd::Buffer* bufp) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root__trace_chg_0\n"); );
    // Init
    Vtb_e203_nice___024root* const __restrict vlSelf VL_ATTR_UNUSED = static_cast<Vtb_e203_nice___024root*>(voidSelf);
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    if (VL_UNLIKELY(!vlSymsp->__Vm_activity)) return;
    // Body
    Vtb_e203_nice___024root__trace_chg_0_sub_0((&vlSymsp->TOP), bufp);
}

void Vtb_e203_nice___024root__trace_chg_0_sub_0(Vtb_e203_nice___024root* vlSelf, VerilatedVcd::Buffer* bufp) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root__trace_chg_0_sub_0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    uint32_t* const oldp VL_ATTR_UNUSED = bufp->oldp(vlSymsp->__Vm_baseCode + 1);
    // Body
    if (VL_UNLIKELY(vlSelfRef.__Vm_traceActivity[1U])) {
        bufp->chgBit(oldp+0,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__calc_start));
        bufp->chgBit(oldp+1,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__retire_mem_holdup));
        bufp->chgBit(oldp+2,(((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid) 
                              | (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid))));
        bufp->chgIData(oldp+3,(((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid)
                                 ? ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_sel)
                                     ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_pong
                                     : vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_ping)
                                 : ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_sel)
                                     ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_pong
                                     : vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_ping))),32);
        bufp->chgBit(oldp+4,(vlSelfRef.tb_e203_nice__DOT____Vcellout__u_nice_core__nice_icb_cmd_valid));
        bufp->chgIData(oldp+5,(((0xfffffffcU & vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr_comb) 
                                + VL_SHIFTL_III(32,32,32, (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_burst_cnt), 2U))),32);
        bufp->chgBit(oldp+6,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read_comb));
        bufp->chgIData(oldp+7,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wdata_aligned),32);
        bufp->chgCData(oldp+8,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wmask_aligned),4);
        bufp->chgBit(oldp+9,(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_rsp_valid));
        bufp->chgBit(oldp+10,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__cfg_16bits_ia));
        bufp->chgBit(oldp+11,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__use_per_channel));
        bufp->chgIData(oldp+12,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__dst_base),32);
        bufp->chgBit(oldp+13,((0U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state))));
        bufp->chgIData(oldp+14,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_wdata),32);
        bufp->chgBit(oldp+15,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_req));
        bufp->chgBit(oldp+16,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__is_csr_read));
        bufp->chgSData(oldp+17,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr),12);
        bufp->chgBit(oldp+18,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_ready));
        bufp->chgIData(oldp+19,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_rdata),32);
        bufp->chgIData(oldp+20,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_lhs_base),32);
        bufp->chgIData(oldp+21,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_rhs_base),32);
        bufp->chgIData(oldp+22,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_dst_base),32);
        bufp->chgIData(oldp+23,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_bias_base),32);
        bufp->chgIData(oldp+24,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_lhs_zp),32);
        bufp->chgIData(oldp+25,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_rhs_zp),32);
        bufp->chgIData(oldp+26,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_dst_zp),32);
        bufp->chgIData(oldp+27,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_q_mult_pt),32);
        bufp->chgIData(oldp+28,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_q_shift_pt),32);
        bufp->chgIData(oldp+29,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_k),32);
        bufp->chgIData(oldp+30,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_n),32);
        bufp->chgIData(oldp+31,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_m),32);
        bufp->chgIData(oldp+32,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_lhs_row_stride_b),32);
        bufp->chgIData(oldp+33,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_dst_row_stride_b),32);
        bufp->chgIData(oldp+34,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_rhs_row_stride_b),32);
        bufp->chgIData(oldp+35,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_act_min),32);
        bufp->chgIData(oldp+36,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_act_max),32);
        bufp->chgBit(oldp+37,((2U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state))));
        bufp->chgBit(oldp+38,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__mma_wb_ready));
        bufp->chgBit(oldp+39,((1U & (~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_sel)
                                         ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__pong_full)
                                         : (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__ping_full))))));
        bufp->chgIData(oldp+40,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_wb_data),32);
        bufp->chgBit(oldp+41,((1U & (~ (((1U & ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_wptr) 
                                                >> 4U)) 
                                         != (1U & ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_rptr) 
                                                   >> 4U))) 
                                        & ((0xfU & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_wptr)) 
                                           == (0xfU 
                                               & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_rptr))))))));
        bufp->chgBit(oldp+42,(((~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read_comb)) 
                               & ((0U != (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state)) 
                                  & (~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__is_last_burst) 
                                        & (0U != (3U 
                                                  & vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr_comb))))))));
        bufp->chgBit(oldp+43,(((IData)(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_rsp_valid) 
                               & (((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read) 
                                   & (((0U == (3U & vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr)) 
                                       & (0U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_state))) 
                                      | (3U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_state)))) 
                                  | ((~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read)) 
                                     & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rd_last_burst))))));
        bufp->chgIData(oldp+44,(((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read_comb)
                                  ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rdata_aligned
                                  : 0U)),32);
        bufp->chgBit(oldp+45,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_ren));
        bufp->chgBit(oldp+46,((((1U & ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_wptr) 
                                       >> 4U)) != (1U 
                                                   & ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_rptr) 
                                                      >> 4U))) 
                               & ((0xfU & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_wptr)) 
                                  == (0xfU & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_rptr))))));
        bufp->chgBit(oldp+47,(((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_rptr) 
                               == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_wptr))));
        bufp->chgQData(oldp+48,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_mem
                                [(0xfU & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_rptr))]),37);
        bufp->chgCData(oldp+50,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_wptr),5);
        bufp->chgCData(oldp+51,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_rptr),5);
        bufp->chgCData(oldp+52,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__burst_cycle_1start),5);
        bufp->chgCData(oldp+53,((3U & vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr_comb)),2);
        bufp->chgIData(oldp+54,((0xfffffffcU & vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr_comb)),32);
        bufp->chgBit(oldp+55,((0U != (3U & vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr_comb))));
        bufp->chgCData(oldp+56,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_burst_cnt),5);
        bufp->chgCData(oldp+57,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__burst_cnt_nxt),5);
        bufp->chgBit(oldp+58,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__fifo_is_read));
        bufp->chgIData(oldp+59,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__fifo_addr),32);
        bufp->chgCData(oldp+60,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__fifo_len),4);
        bufp->chgBit(oldp+61,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read));
        bufp->chgIData(oldp+62,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr),32);
        bufp->chgCData(oldp+63,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_len_0start),4);
        bufp->chgCData(oldp+64,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_burst_cnt),5);
        bufp->chgCData(oldp+65,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_burst_cnt_nxt),5);
        bufp->chgIData(oldp+66,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wdata_buf),32);
        bufp->chgCData(oldp+67,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wmask_buf),4);
        bufp->chgBit(oldp+68,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wdata_buf_valid));
        bufp->chgIData(oldp+69,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rdata_buf),32);
        bufp->chgBit(oldp+70,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rdata_buf_valid));
        bufp->chgIData(oldp+71,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rdata_aligned),32);
        bufp->chgCData(oldp+72,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state),2);
        bufp->chgCData(oldp+73,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state_nxt),2);
        bufp->chgCData(oldp+74,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_state),2);
        bufp->chgCData(oldp+75,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_state_nxt),2);
        bufp->chgBit(oldp+76,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fire));
        bufp->chgBit(oldp+77,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__is_last_burst));
        bufp->chgBit(oldp+78,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rd_last_burst));
        bufp->chgBit(oldp+79,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__last_beat_sent));
        bufp->chgIData(oldp+80,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr_comb),32);
        bufp->chgCData(oldp+81,(((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_ren)
                                  ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__fifo_len)
                                  : (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_len_0start))),4);
        bufp->chgBit(oldp+82,((0U != (3U & vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr))));
        bufp->chgCData(oldp+83,((0x1fU & ((IData)(1U) 
                                          + ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_len_0start) 
                                             + (0U 
                                                != 
                                                (3U 
                                                 & vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr)))))),5);
        bufp->chgBit(oldp+84,(((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read_comb) 
                               & (IData)(vlSelfRef.tb_e203_nice__DOT____Vcellout__u_nice_core__nice_icb_cmd_valid))));
        bufp->chgBit(oldp+85,(((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT____VdfgRegularize_hc6488b08_0_5) 
                               & (IData)(vlSelfRef.tb_e203_nice__DOT____Vcellout__u_nice_core__nice_icb_cmd_valid))));
        bufp->chgCData(oldp+86,((0x1fU & VL_SHIFTL_III(5,5,32, 
                                                       (3U 
                                                        & vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr_comb), 3U))),5);
        bufp->chgBit(oldp+87,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__state));
        bufp->chgBit(oldp+88,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__wb_handshake));
        bufp->chgCData(oldp+89,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state),2);
        bufp->chgCData(oldp+90,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__cycle_cnt),8);
        bufp->chgBit(oldp+91,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid));
        bufp->chgIData(oldp+92,(((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_sel)
                                  ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_pong
                                  : vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_ping)),32);
        bufp->chgBit(oldp+93,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid));
        bufp->chgIData(oldp+94,(((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_sel)
                                  ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_pong
                                  : vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_ping)),32);
        bufp->chgBit(oldp+95,(((~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid)) 
                               & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid))));
        bufp->chgIData(oldp+96,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_ping),32);
        bufp->chgIData(oldp+97,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_pong),32);
        bufp->chgBit(oldp+98,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__ping_full));
        bufp->chgBit(oldp+99,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__pong_full));
        bufp->chgBit(oldp+100,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_sel));
        bufp->chgBit(oldp+101,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_sel));
        bufp->chgBit(oldp+102,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_hsked));
        bufp->chgIData(oldp+103,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_ping),32);
        bufp->chgIData(oldp+104,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_pong),32);
        bufp->chgBit(oldp+105,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__ping_full));
        bufp->chgBit(oldp+106,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__pong_full));
        bufp->chgBit(oldp+107,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wr_sel));
        bufp->chgBit(oldp+108,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_sel));
    }
    if (VL_UNLIKELY((vlSelfRef.__Vm_traceActivity[1U] 
                     | vlSelfRef.__Vm_traceActivity
                     [2U]))) {
        bufp->chgBit(oldp+109,(((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_inst)
                                 ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_ready)
                                 : (0U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state)))));
        bufp->chgBit(oldp+110,(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_cmd_valid));
        bufp->chgIData(oldp+111,(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_cmd_addr),32);
        bufp->chgBit(oldp+112,(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_cmd_read));
        bufp->chgIData(oldp+113,(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_cmd_wdata),32);
        bufp->chgCData(oldp+114,(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_cmd_wmask),4);
    }
    if (VL_UNLIKELY(vlSelfRef.__Vm_traceActivity[2U])) {
        bufp->chgIData(oldp+115,(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_inst),32);
        bufp->chgIData(oldp+116,(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_rs1),32);
        bufp->chgIData(oldp+117,(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_rs2),32);
        bufp->chgCData(oldp+118,((0x7fU & vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_inst)),7);
        bufp->chgCData(oldp+119,((7U & (vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_inst 
                                        >> 0xcU))),3);
        bufp->chgCData(oldp+120,((vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_inst 
                                  >> 0x19U)),7);
        bufp->chgSData(oldp+121,((vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_inst 
                                  >> 0x14U)),12);
        bufp->chgCData(oldp+122,((7U & vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_rs2)),3);
        bufp->chgCData(oldp+123,((3U & (vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_rs2 
                                        >> 3U))),2);
        bufp->chgCData(oldp+124,((3U & (vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_rs2 
                                        >> 5U))),2);
        bufp->chgCData(oldp+125,((3U & (vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_rs2 
                                        >> 7U))),2);
        bufp->chgBit(oldp+126,((1U & (vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_rs2 
                                      >> 9U))));
        bufp->chgBit(oldp+127,((2U == (3U & (vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_rs2 
                                             >> 7U)))));
        bufp->chgBit(oldp+128,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_mat_mult_t));
        bufp->chgBit(oldp+129,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_wr));
        bufp->chgBit(oldp+130,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_rd));
        bufp->chgBit(oldp+131,(((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_mat_mult_t) 
                                | (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_inst))));
        bufp->chgBit(oldp+132,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_inst));
    }
    bufp->chgBit(oldp+133,(vlSelfRef.tb_e203_nice__DOT__clk));
    bufp->chgBit(oldp+134,(vlSelfRef.tb_e203_nice__DOT__rst_n));
    bufp->chgIData(oldp+135,(vlSelfRef.tb_e203_nice__DOT__send_csr_read__Vstatic__read_value),32);
    bufp->chgIData(oldp+136,(vlSelfRef.tb_e203_nice__DOT__test_response_backpressure__Vstatic__read_value),32);
    bufp->chgIData(oldp+137,(vlSelfRef.tb_e203_nice__DOT__test_request_backpressure__Vstatic__read_value),32);
    bufp->chgBit(oldp+138,(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_valid));
    bufp->chgBit(oldp+139,(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.rsp_ready));
    bufp->chgBit(oldp+140,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__inst_handshake));
    bufp->chgBit(oldp+141,((((~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid)) 
                             & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid)) 
                            & (IData)(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.rsp_ready))));
    bufp->chgBit(oldp+142,(((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid) 
                            & (IData)(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.rsp_ready))));
    bufp->chgBit(oldp+143,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_hsked));
    bufp->chgBit(oldp+144,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_hsked));
    bufp->chgBit(oldp+145,(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_rsp_ready));
}

void Vtb_e203_nice___024root__trace_cleanup(void* voidSelf, VerilatedVcd* /*unused*/) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root__trace_cleanup\n"); );
    // Init
    Vtb_e203_nice___024root* const __restrict vlSelf VL_ATTR_UNUSED = static_cast<Vtb_e203_nice___024root*>(voidSelf);
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    // Body
    vlSymsp->__Vm_activity = false;
    vlSymsp->TOP.__Vm_traceActivity[0U] = 0U;
    vlSymsp->TOP.__Vm_traceActivity[1U] = 0U;
    vlSymsp->TOP.__Vm_traceActivity[2U] = 0U;
}
