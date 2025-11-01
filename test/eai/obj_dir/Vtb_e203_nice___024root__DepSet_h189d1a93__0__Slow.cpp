// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vtb_e203_nice.h for the primary calling header

#include "Vtb_e203_nice__pch.h"
#include "Vtb_e203_nice__Syms.h"
#include "Vtb_e203_nice___024root.h"

VL_ATTR_COLD void Vtb_e203_nice_nice_if___eval_static__TOP__tb_e203_nice__DOT__nice_if_inst(Vtb_e203_nice_nice_if* vlSelf);

VL_ATTR_COLD void Vtb_e203_nice___024root___eval_static(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___eval_static\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    Vtb_e203_nice_nice_if___eval_static__TOP__tb_e203_nice__DOT__nice_if_inst((&vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst));
    vlSelfRef.__Vm_traceActivity[2U] = 1U;
    vlSelfRef.__Vm_traceActivity[1U] = 1U;
    vlSelfRef.__Vm_traceActivity[0U] = 1U;
}

VL_ATTR_COLD void Vtb_e203_nice___024root___eval_initial__TOP(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___eval_initial__TOP\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_rsp_ready = 1U;
    vlSelfRef.tb_e203_nice__DOT__clk = 0U;
}

#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_e203_nice___024root___dump_triggers__stl(Vtb_e203_nice___024root* vlSelf);
#endif  // VL_DEBUG

VL_ATTR_COLD void Vtb_e203_nice___024root___eval_triggers__stl(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___eval_triggers__stl\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelfRef.__VstlTriggered.set(0U, (IData)(vlSelfRef.__VstlFirstIteration));
#ifdef VL_DEBUG
    if (VL_UNLIKELY(vlSymsp->_vm_contextp__->debug())) {
        Vtb_e203_nice___024root___dump_triggers__stl(vlSelf);
    }
#endif
}

extern const VlUnpacked<CData/*1:0*/, 64> Vtb_e203_nice__ConstPool__TABLE_hb06abf12_0;

VL_ATTR_COLD void Vtb_e203_nice___024root___stl_sequent__TOP__0(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___stl_sequent__TOP__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    CData/*5:0*/ __Vtableidx1;
    __Vtableidx1 = 0;
    // Body
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__mma_wb_valid 
        = (2U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_hsked 
        = ((~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_sel)
                ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__pong_full)
                : (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__ping_full))) 
           & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_req));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__mma_wb_ready 
        = (1U & (~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wr_sel)
                     ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__pong_full)
                     : (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__ping_full))));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_mat_mult_t 
        = (IData)((0x200702bU == (0xfe00707fU & vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_inst)));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid 
        = ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_sel)
            ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__pong_full)
            : (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__ping_full));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_wr 
        = (IData)((0x207bU == (0x707fU & vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_inst)));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_rd 
        = (IData)((0x407bU == (0x707fU & vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_inst)));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid 
        = ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_sel)
            ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__pong_full)
            : (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__ping_full));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_rdata 
        = (((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_req) 
            & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__is_csr_read))
            ? ((0x800U & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))
                ? 0U : ((0x400U & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))
                         ? ((0x200U & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))
                             ? ((0x100U & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))
                                 ? ((0x80U & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))
                                     ? ((0x40U & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))
                                         ? ((0x20U 
                                             & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))
                                             ? 0U : 
                                            ((0x10U 
                                              & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))
                                              ? ((8U 
                                                  & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))
                                                  ? 0U
                                                  : 
                                                 ((4U 
                                                   & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))
                                                   ? 0U
                                                   : 
                                                  ((2U 
                                                    & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))
                                                    ? 0U
                                                    : 
                                                   ((1U 
                                                     & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))
                                                     ? 0U
                                                     : vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_act_max))))
                                              : ((8U 
                                                  & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))
                                                  ? 
                                                 ((4U 
                                                   & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))
                                                   ? 
                                                  ((2U 
                                                    & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))
                                                    ? 
                                                   ((1U 
                                                     & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))
                                                     ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_act_min
                                                     : vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_q_shift_pt)
                                                    : 
                                                   ((1U 
                                                     & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))
                                                     ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_q_mult_pt
                                                     : vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_dst_zp))
                                                   : 
                                                  ((2U 
                                                    & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))
                                                    ? 
                                                   ((1U 
                                                     & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))
                                                     ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_rhs_zp
                                                     : vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_lhs_zp)
                                                    : 
                                                   ((1U 
                                                     & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))
                                                     ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_rhs_row_stride_b
                                                     : vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_lhs_row_stride_b)))
                                                  : 
                                                 ((4U 
                                                   & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))
                                                   ? 
                                                  ((2U 
                                                    & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))
                                                    ? 
                                                   ((1U 
                                                     & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))
                                                     ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_dst_row_stride_b
                                                     : vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_m)
                                                    : 
                                                   ((1U 
                                                     & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))
                                                     ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_n
                                                     : vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_k))
                                                   : 
                                                  ((2U 
                                                    & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))
                                                    ? 
                                                   ((1U 
                                                     & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))
                                                     ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_bias_base
                                                     : vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_dst_base)
                                                    : 
                                                   ((1U 
                                                     & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))
                                                     ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_rhs_base
                                                     : vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_lhs_base))))))
                                         : 0U) : 0U)
                                 : 0U) : 0U) : 0U))
            : 0U);
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__fifo_len 
        = (0xfU & (IData)((vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_mem
                           [(0xfU & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_rptr))] 
                           >> 0x20U)));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__fifo_is_read 
        = (1U & (IData)((vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_mem
                         [(0xfU & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_rptr))] 
                         >> 0x24U)));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__fifo_addr 
        = (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_mem
                  [(0xfU & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_rptr))]);
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rd_last_burst 
        = ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_burst_cnt) 
           == ((0x1fU & ((IData)(1U) + ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_len_0start) 
                                        + (0U != (3U 
                                                  & vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr))))) 
               - (IData)(1U)));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__wb_handshake 
        = ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__mma_wb_ready) 
           & (2U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state)));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_inst 
        = ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_wr) 
           | (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_rd));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_hsked 
        = ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid) 
           & (IData)(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.rsp_ready));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_hsked 
        = (((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid) 
            & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid))) 
           & (IData)(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.rsp_ready));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_wb_data 
        = ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__is_csr_read)
            ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_rdata
            : 0U);
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_burst_cnt_nxt 
        = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_burst_cnt;
    if (vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_rsp_valid) {
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_burst_cnt_nxt 
            = ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rd_last_burst)
                ? 0U : (0x1fU & ((IData)(1U) + (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_burst_cnt))));
    }
    __Vtableidx1 = (4U | (((IData)(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_rsp_valid) 
                           << 5U) | (((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rd_last_burst) 
                                      << 4U) | (((IData)(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_rsp_valid) 
                                                 << 3U) 
                                                | (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_state)))));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_state_nxt 
        = Vtb_e203_nice__ConstPool__TABLE_hb06abf12_0
        [__Vtableidx1];
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_ren 
        = (((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_rptr) 
            != (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_wptr)) 
           & (((0U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state)) 
               & (0U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_state))) 
              | ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rd_last_burst) 
                 & (IData)(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_rsp_valid))));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__inst_handshake 
        = ((IData)(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_valid) 
           & (((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_inst)
                ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_ready)
                : (0U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state))) 
              & ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_mat_mult_t) 
                 | (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_inst))));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read_comb 
        = ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rd_last_burst)
            ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read)
            : ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_ren)
                ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__fifo_is_read)
                : (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read)));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr_comb 
        = ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_ren)
            ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__fifo_addr
            : vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr);
    if (vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read_comb) {
        vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_cmd_read = 1U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rdata_aligned = 0U;
        if ((0U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_state))) {
            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rdata_aligned = 0U;
        } else if ((3U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_state))) {
            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rdata_aligned 
                = (((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rdata_buf_valid) 
                    & (0U != (3U & vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr)))
                    ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rdata_buf
                    : 0U);
        }
    } else {
        vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_cmd_read = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rdata_aligned = 0U;
    }
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_cmd_addr 
        = ((0xfffffffcU & vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr_comb) 
           + VL_SHIFTL_III(32,32,32, (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_burst_cnt), 2U));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__burst_cycle_1start 
        = (0x1fU & ((IData)(1U) + (((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_ren)
                                     ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__fifo_len)
                                     : (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_len_0start)) 
                                   + (0U != (3U & vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr_comb)))));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__is_last_burst 
        = ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_burst_cnt) 
           == ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__burst_cycle_1start) 
               - (IData)(1U)));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wdata_aligned = 0U;
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wmask_aligned = 0U;
    if (((1U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state)) 
         & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read_comb)))) {
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wdata_aligned = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wmask_aligned = 0U;
    } else if (((3U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state)) 
                & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read_comb)))) {
        if (vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__is_last_burst) {
            if ((0U != (3U & vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr_comb))) {
                vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wdata_aligned 
                    = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wdata_buf;
                vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wmask_aligned 
                    = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wmask_buf;
            } else {
                vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wdata_aligned = 0U;
                vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wmask_aligned = 0U;
            }
        } else {
            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wdata_aligned 
                = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wdata_buf;
            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wmask_aligned 
                = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wmask_buf;
        }
    }
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT____VdfgRegularize_hc6488b08_0_5 
        = ((~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read_comb)) 
           & ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wdata_buf_valid) 
              & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__is_last_burst)));
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_cmd_wdata 
        = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wdata_aligned;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_cmd_wmask 
        = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wmask_aligned;
    vlSelfRef.tb_e203_nice__DOT____Vcellout__u_nice_core__nice_icb_cmd_valid 
        = ((0U != (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state)) 
           & ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read_comb) 
              | ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT____VdfgRegularize_hc6488b08_0_5) 
                 & (0U != (3U & vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr_comb)))));
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_cmd_valid 
        = vlSelfRef.tb_e203_nice__DOT____Vcellout__u_nice_core__nice_icb_cmd_valid;
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fire 
        = (((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT____VdfgRegularize_hc6488b08_0_5) 
            | (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read_comb)) 
           & (IData)(vlSelfRef.tb_e203_nice__DOT____Vcellout__u_nice_core__nice_icb_cmd_valid));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state_nxt 
        = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state;
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__burst_cnt_nxt 
        = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_burst_cnt;
    if ((0U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state))) {
        if (vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_ren) {
            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state_nxt = 1U;
            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__burst_cnt_nxt = 0U;
        }
    } else if ((1U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state))) {
        if (vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fire) {
            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state_nxt 
                = (((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_burst_cnt) 
                    == ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__burst_cycle_1start) 
                        - (IData)(1U))) ? 0U : 3U);
            if (((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_burst_cnt) 
                 != ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__burst_cycle_1start) 
                     - (IData)(1U)))) {
                vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__burst_cnt_nxt 
                    = (0x1fU & ((IData)(1U) + (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_burst_cnt)));
            }
        }
    } else if ((3U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state))) {
        if (vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fire) {
            if (((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_burst_cnt) 
                 == ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__burst_cycle_1start) 
                     - (IData)(1U)))) {
                vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state_nxt = 0U;
                vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__burst_cnt_nxt = 0U;
            } else {
                vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__burst_cnt_nxt 
                    = (0x1fU & ((IData)(1U) + (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_burst_cnt)));
            }
        }
    }
}
