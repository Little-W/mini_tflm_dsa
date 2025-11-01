// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vtb_e203_nice.h for the primary calling header

#include "Vtb_e203_nice__pch.h"
#include "Vtb_e203_nice__Syms.h"
#include "Vtb_e203_nice___024root.h"

VL_INLINE_OPT VlCoroutine Vtb_e203_nice___024root___eval_initial__TOP__Vtiming__0(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___eval_initial__TOP__Vtiming__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    SData/*11:0*/ __Vtask_tb_e203_nice__DOT__send_csr_write__0__csr_addr;
    __Vtask_tb_e203_nice__DOT__send_csr_write__0__csr_addr = 0;
    IData/*31:0*/ __Vtask_tb_e203_nice__DOT__send_csr_write__0__value;
    __Vtask_tb_e203_nice__DOT__send_csr_write__0__value = 0;
    SData/*11:0*/ __Vtask_tb_e203_nice__DOT__send_csr_write__1__csr_addr;
    __Vtask_tb_e203_nice__DOT__send_csr_write__1__csr_addr = 0;
    IData/*31:0*/ __Vtask_tb_e203_nice__DOT__send_csr_write__1__value;
    __Vtask_tb_e203_nice__DOT__send_csr_write__1__value = 0;
    SData/*11:0*/ __Vtask_tb_e203_nice__DOT__send_csr_read__2__csr_addr;
    __Vtask_tb_e203_nice__DOT__send_csr_read__2__csr_addr = 0;
    IData/*31:0*/ __Vtask_tb_e203_nice__DOT__send_csr_read__2__expected_value;
    __Vtask_tb_e203_nice__DOT__send_csr_read__2__expected_value = 0;
    SData/*11:0*/ __Vtask_tb_e203_nice__DOT__send_csr_read__3__csr_addr;
    __Vtask_tb_e203_nice__DOT__send_csr_read__3__csr_addr = 0;
    IData/*31:0*/ __Vtask_tb_e203_nice__DOT__send_csr_read__3__expected_value;
    __Vtask_tb_e203_nice__DOT__send_csr_read__3__expected_value = 0;
    IData/*31:0*/ __Vtask_tb_e203_nice__DOT__send_mat_mult__4__out_addr;
    __Vtask_tb_e203_nice__DOT__send_mat_mult__4__out_addr = 0;
    IData/*31:0*/ __Vtask_tb_e203_nice__DOT__send_mat_mult__4__cfg;
    __Vtask_tb_e203_nice__DOT__send_mat_mult__4__cfg = 0;
    // Body
    vlSymsp->_vm_contextp__->dumpfile(std::string{"wave.vcd"});
    vlSymsp->_traceDumpOpen();
    vlSelfRef.tb_e203_nice__DOT__rst_n = 0U;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_valid = 0U;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.rsp_ready = 1U;
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         79);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         79);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         79);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         79);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         79);
    vlSelfRef.tb_e203_nice__DOT__rst_n = 1U;
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         81);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         81);
    VL_WRITEF_NX("[%0t] === Test 1: CSR Write (csrwr) to MULT_LHS_ROWS (0x7C6) ===\n",0,
                 64,VL_TIME_UNITED_Q(1000),-9);
    __Vtask_tb_e203_nice__DOT__send_csr_write__0__value = 0x10U;
    __Vtask_tb_e203_nice__DOT__send_csr_write__0__csr_addr = 0x7c6U;
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         115);
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_valid = 1U;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_inst 
        = (0xa07bU | ((IData)(__Vtask_tb_e203_nice__DOT__send_csr_write__0__csr_addr) 
                      << 0x14U));
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_rs1 
        = __Vtask_tb_e203_nice__DOT__send_csr_write__0__value;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_rs2 = 0U;
    while ((1U & (~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_inst)
                      ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_ready)
                      : (0U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state)))))) {
        co_await vlSelfRef.__VtrigSched_h3ada226f__0.trigger(1U, 
                                                             nullptr, 
                                                             "@([changed] (tb_e203_nice.u_nice_core.u_decode_dispatch.is_csr_inst ? tb_e203_nice.u_nice_core.csr_ready : (2'h0 == tb_e203_nice.u_nice_core.u_mma_top.state)))", 
                                                             "tb_e203_nice.sv", 
                                                             121);
    }
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         122);
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_valid = 0U;
    while ((1U & (~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid) 
                     | (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid))))) {
        co_await vlSelfRef.__VtrigSched_hcf9bbd92__0.trigger(1U, 
                                                             nullptr, 
                                                             "@([changed] (tb_e203_nice.u_nice_core.u_wbu.csr_buf_rd_valid | tb_e203_nice.u_nice_core.u_wbu.mma_buf_rd_valid))", 
                                                             "tb_e203_nice.sv", 
                                                             124);
    }
    VL_WRITEF_NX("[%0t]   CSR[0x%03x] <= 0x%08x, err=0\n",0,
                 64,VL_TIME_UNITED_Q(1000),-9,12,(IData)(__Vtask_tb_e203_nice__DOT__send_csr_write__0__csr_addr),
                 32,__Vtask_tb_e203_nice__DOT__send_csr_write__0__value);
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         126);
    VL_WRITEF_NX("[%0t] === Test 2: CSR Write (csrwr) to MULT_RHS_COLS (0x7C7) ===\n",0,
                 64,VL_TIME_UNITED_Q(1000),-9);
    __Vtask_tb_e203_nice__DOT__send_csr_write__1__value = 8U;
    __Vtask_tb_e203_nice__DOT__send_csr_write__1__csr_addr = 0x7c7U;
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         115);
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_valid = 1U;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_inst 
        = (0xa07bU | ((IData)(__Vtask_tb_e203_nice__DOT__send_csr_write__1__csr_addr) 
                      << 0x14U));
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_rs1 
        = __Vtask_tb_e203_nice__DOT__send_csr_write__1__value;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_rs2 = 0U;
    while ((1U & (~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_inst)
                      ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_ready)
                      : (0U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state)))))) {
        co_await vlSelfRef.__VtrigSched_h3ada226f__0.trigger(1U, 
                                                             nullptr, 
                                                             "@([changed] (tb_e203_nice.u_nice_core.u_decode_dispatch.is_csr_inst ? tb_e203_nice.u_nice_core.csr_ready : (2'h0 == tb_e203_nice.u_nice_core.u_mma_top.state)))", 
                                                             "tb_e203_nice.sv", 
                                                             121);
    }
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         122);
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_valid = 0U;
    while ((1U & (~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid) 
                     | (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid))))) {
        co_await vlSelfRef.__VtrigSched_hcf9bbd92__0.trigger(1U, 
                                                             nullptr, 
                                                             "@([changed] (tb_e203_nice.u_nice_core.u_wbu.csr_buf_rd_valid | tb_e203_nice.u_nice_core.u_wbu.mma_buf_rd_valid))", 
                                                             "tb_e203_nice.sv", 
                                                             124);
    }
    VL_WRITEF_NX("[%0t]   CSR[0x%03x] <= 0x%08x, err=0\n",0,
                 64,VL_TIME_UNITED_Q(1000),-9,12,(IData)(__Vtask_tb_e203_nice__DOT__send_csr_write__1__csr_addr),
                 32,__Vtask_tb_e203_nice__DOT__send_csr_write__1__value);
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         126);
    VL_WRITEF_NX("[%0t] === Test 3: CSR Read (csrrd) from MULT_LHS_ROWS ===\n",0,
                 64,VL_TIME_UNITED_Q(1000),-9);
    __Vtask_tb_e203_nice__DOT__send_csr_read__2__expected_value = 0x10U;
    __Vtask_tb_e203_nice__DOT__send_csr_read__2__csr_addr = 0x7c6U;
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         132);
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_valid = 1U;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_inst 
        = (0x40fbU | ((IData)(__Vtask_tb_e203_nice__DOT__send_csr_read__2__csr_addr) 
                      << 0x14U));
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_rs1 = 0U;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_rs2 = 0U;
    while ((1U & (~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_inst)
                      ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_ready)
                      : (0U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state)))))) {
        co_await vlSelfRef.__VtrigSched_h3ada226f__0.trigger(1U, 
                                                             nullptr, 
                                                             "@([changed] (tb_e203_nice.u_nice_core.u_decode_dispatch.is_csr_inst ? tb_e203_nice.u_nice_core.csr_ready : (2'h0 == tb_e203_nice.u_nice_core.u_mma_top.state)))", 
                                                             "tb_e203_nice.sv", 
                                                             138);
    }
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         139);
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_valid = 0U;
    while ((1U & (~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid) 
                     | (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid))))) {
        co_await vlSelfRef.__VtrigSched_hcf9bbd92__0.trigger(1U, 
                                                             nullptr, 
                                                             "@([changed] (tb_e203_nice.u_nice_core.u_wbu.csr_buf_rd_valid | tb_e203_nice.u_nice_core.u_wbu.mma_buf_rd_valid))", 
                                                             "tb_e203_nice.sv", 
                                                             141);
    }
    vlSelfRef.tb_e203_nice__DOT__send_csr_read__Vstatic__read_value 
        = ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid)
            ? ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_sel)
                ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_pong
                : vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_ping)
            : ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_sel)
                ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_pong
                : vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_ping));
    if (VL_UNLIKELY((vlSelfRef.tb_e203_nice__DOT__send_csr_read__Vstatic__read_value 
                     != __Vtask_tb_e203_nice__DOT__send_csr_read__2__expected_value))) {
        VL_WRITEF_NX("[%0t] ERROR: CSR[0x%03x] read mismatch! Expected: 0x%08x, Got: 0x%08x\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,12,
                     (IData)(__Vtask_tb_e203_nice__DOT__send_csr_read__2__csr_addr),
                     32,__Vtask_tb_e203_nice__DOT__send_csr_read__2__expected_value,
                     32,vlSelfRef.tb_e203_nice__DOT__send_csr_read__Vstatic__read_value);
        co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                             nullptr, 
                                                             "@(posedge tb_e203_nice.clk)", 
                                                             "tb_e203_nice.sv", 
                                                             147);
        co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                             nullptr, 
                                                             "@(posedge tb_e203_nice.clk)", 
                                                             "tb_e203_nice.sv", 
                                                             147);
        co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                             nullptr, 
                                                             "@(posedge tb_e203_nice.clk)", 
                                                             "tb_e203_nice.sv", 
                                                             147);
        co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                             nullptr, 
                                                             "@(posedge tb_e203_nice.clk)", 
                                                             "tb_e203_nice.sv", 
                                                             147);
        co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                             nullptr, 
                                                             "@(posedge tb_e203_nice.clk)", 
                                                             "tb_e203_nice.sv", 
                                                             147);
        co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                             nullptr, 
                                                             "@(posedge tb_e203_nice.clk)", 
                                                             "tb_e203_nice.sv", 
                                                             147);
        co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                             nullptr, 
                                                             "@(posedge tb_e203_nice.clk)", 
                                                             "tb_e203_nice.sv", 
                                                             147);
        co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                             nullptr, 
                                                             "@(posedge tb_e203_nice.clk)", 
                                                             "tb_e203_nice.sv", 
                                                             147);
        co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                             nullptr, 
                                                             "@(posedge tb_e203_nice.clk)", 
                                                             "tb_e203_nice.sv", 
                                                             147);
        co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                             nullptr, 
                                                             "@(posedge tb_e203_nice.clk)", 
                                                             "tb_e203_nice.sv", 
                                                             147);
        VL_WRITEF_NX("[%0t] %%Fatal: tb_e203_nice.sv:148: Assertion failed in %Ntb_e203_nice.send_csr_read: CSR verification failed\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,vlSymsp->name());
        VL_STOP_MT("tb_e203_nice.sv", 148, "");
    } else {
        VL_WRITEF_NX("[%0t]   CSR[0x%03x] => 0x%08x (PASS), err=0\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,12,
                     (IData)(__Vtask_tb_e203_nice__DOT__send_csr_read__2__csr_addr),
                     32,vlSelfRef.tb_e203_nice__DOT__send_csr_read__Vstatic__read_value);
    }
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         153);
    VL_WRITEF_NX("[%0t] === Test 4: CSR Read (csrrd) from MULT_RHS_COLS ===\n",0,
                 64,VL_TIME_UNITED_Q(1000),-9);
    __Vtask_tb_e203_nice__DOT__send_csr_read__3__expected_value = 8U;
    __Vtask_tb_e203_nice__DOT__send_csr_read__3__csr_addr = 0x7c7U;
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         132);
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_valid = 1U;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_inst 
        = (0x40fbU | ((IData)(__Vtask_tb_e203_nice__DOT__send_csr_read__3__csr_addr) 
                      << 0x14U));
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_rs1 = 0U;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_rs2 = 0U;
    while ((1U & (~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_inst)
                      ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_ready)
                      : (0U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state)))))) {
        co_await vlSelfRef.__VtrigSched_h3ada226f__0.trigger(1U, 
                                                             nullptr, 
                                                             "@([changed] (tb_e203_nice.u_nice_core.u_decode_dispatch.is_csr_inst ? tb_e203_nice.u_nice_core.csr_ready : (2'h0 == tb_e203_nice.u_nice_core.u_mma_top.state)))", 
                                                             "tb_e203_nice.sv", 
                                                             138);
    }
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         139);
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_valid = 0U;
    while ((1U & (~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid) 
                     | (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid))))) {
        co_await vlSelfRef.__VtrigSched_hcf9bbd92__0.trigger(1U, 
                                                             nullptr, 
                                                             "@([changed] (tb_e203_nice.u_nice_core.u_wbu.csr_buf_rd_valid | tb_e203_nice.u_nice_core.u_wbu.mma_buf_rd_valid))", 
                                                             "tb_e203_nice.sv", 
                                                             141);
    }
    vlSelfRef.tb_e203_nice__DOT__send_csr_read__Vstatic__read_value 
        = ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid)
            ? ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_sel)
                ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_pong
                : vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_ping)
            : ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_sel)
                ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_pong
                : vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_ping));
    if (VL_UNLIKELY((vlSelfRef.tb_e203_nice__DOT__send_csr_read__Vstatic__read_value 
                     != __Vtask_tb_e203_nice__DOT__send_csr_read__3__expected_value))) {
        VL_WRITEF_NX("[%0t] ERROR: CSR[0x%03x] read mismatch! Expected: 0x%08x, Got: 0x%08x\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,12,
                     (IData)(__Vtask_tb_e203_nice__DOT__send_csr_read__3__csr_addr),
                     32,__Vtask_tb_e203_nice__DOT__send_csr_read__3__expected_value,
                     32,vlSelfRef.tb_e203_nice__DOT__send_csr_read__Vstatic__read_value);
        co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                             nullptr, 
                                                             "@(posedge tb_e203_nice.clk)", 
                                                             "tb_e203_nice.sv", 
                                                             147);
        co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                             nullptr, 
                                                             "@(posedge tb_e203_nice.clk)", 
                                                             "tb_e203_nice.sv", 
                                                             147);
        co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                             nullptr, 
                                                             "@(posedge tb_e203_nice.clk)", 
                                                             "tb_e203_nice.sv", 
                                                             147);
        co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                             nullptr, 
                                                             "@(posedge tb_e203_nice.clk)", 
                                                             "tb_e203_nice.sv", 
                                                             147);
        co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                             nullptr, 
                                                             "@(posedge tb_e203_nice.clk)", 
                                                             "tb_e203_nice.sv", 
                                                             147);
        co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                             nullptr, 
                                                             "@(posedge tb_e203_nice.clk)", 
                                                             "tb_e203_nice.sv", 
                                                             147);
        co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                             nullptr, 
                                                             "@(posedge tb_e203_nice.clk)", 
                                                             "tb_e203_nice.sv", 
                                                             147);
        co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                             nullptr, 
                                                             "@(posedge tb_e203_nice.clk)", 
                                                             "tb_e203_nice.sv", 
                                                             147);
        co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                             nullptr, 
                                                             "@(posedge tb_e203_nice.clk)", 
                                                             "tb_e203_nice.sv", 
                                                             147);
        co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                             nullptr, 
                                                             "@(posedge tb_e203_nice.clk)", 
                                                             "tb_e203_nice.sv", 
                                                             147);
        VL_WRITEF_NX("[%0t] %%Fatal: tb_e203_nice.sv:148: Assertion failed in %Ntb_e203_nice.send_csr_read: CSR verification failed\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,vlSymsp->name());
        VL_STOP_MT("tb_e203_nice.sv", 148, "");
    } else {
        VL_WRITEF_NX("[%0t]   CSR[0x%03x] => 0x%08x (PASS), err=0\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,12,
                     (IData)(__Vtask_tb_e203_nice__DOT__send_csr_read__3__csr_addr),
                     32,vlSelfRef.tb_e203_nice__DOT__send_csr_read__Vstatic__read_value);
    }
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         153);
    VL_WRITEF_NX("[%0t] === Test 5: Matrix Multiply (mat_mult_t) ===\n",0,
                 64,VL_TIME_UNITED_Q(1000),-9);
    __Vtask_tb_e203_nice__DOT__send_mat_mult__4__cfg = 0U;
    __Vtask_tb_e203_nice__DOT__send_mat_mult__4__out_addr = 0x1000U;
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         158);
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_valid = 1U;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_inst = 0x220f1abU;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_rs1 
        = __Vtask_tb_e203_nice__DOT__send_mat_mult__4__out_addr;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_rs2 
        = __Vtask_tb_e203_nice__DOT__send_mat_mult__4__cfg;
    while ((1U & (~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_inst)
                      ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_ready)
                      : (0U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state)))))) {
        co_await vlSelfRef.__VtrigSched_h3ada226f__0.trigger(1U, 
                                                             nullptr, 
                                                             "@([changed] (tb_e203_nice.u_nice_core.u_decode_dispatch.is_csr_inst ? tb_e203_nice.u_nice_core.csr_ready : (2'h0 == tb_e203_nice.u_nice_core.u_mma_top.state)))", 
                                                             "tb_e203_nice.sv", 
                                                             166);
    }
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         167);
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_valid = 0U;
    while ((1U & (~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid) 
                     | (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid))))) {
        co_await vlSelfRef.__VtrigSched_hcf9bbd92__0.trigger(1U, 
                                                             nullptr, 
                                                             "@([changed] (tb_e203_nice.u_nice_core.u_wbu.csr_buf_rd_valid | tb_e203_nice.u_nice_core.u_wbu.mma_buf_rd_valid))", 
                                                             "tb_e203_nice.sv", 
                                                             169);
    }
    VL_WRITEF_NX("[%0t]   mat_mult_t started, status=0x%08x, err=0\n",0,
                 64,VL_TIME_UNITED_Q(1000),-9,32,((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid)
                                                   ? 
                                                  ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_sel)
                                                    ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_pong
                                                    : vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_ping)
                                                   : 
                                                  ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_sel)
                                                    ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_pong
                                                    : vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_ping)));
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         172);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         98);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         98);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         98);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         98);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         98);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         98);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         98);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         98);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         98);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         98);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         98);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         98);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         98);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         98);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         98);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         98);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         98);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         98);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         98);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         98);
    VL_WRITEF_NX("[%0t] === Test 6: Response Backpressure Test ===\n",0,
                 64,VL_TIME_UNITED_Q(1000),-9);
    VL_WRITEF_NX("[%0t]   Step 1: Send CSR write with rsp_ready=1\n",0,
                 64,VL_TIME_UNITED_Q(1000),-9);
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         179);
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_valid = 1U;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_inst = 0x7c80a07bU;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_rs1 = 0xdeadbeefU;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_rs2 = 0U;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__rsp_ready = 1U;
    while ((1U & (~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_inst)
                      ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_ready)
                      : (0U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state)))))) {
        co_await vlSelfRef.__VtrigSched_h3ada226f__0.trigger(1U, 
                                                             nullptr, 
                                                             "@([changed] (tb_e203_nice.u_nice_core.u_decode_dispatch.is_csr_inst ? tb_e203_nice.u_nice_core.csr_ready : (2'h0 == tb_e203_nice.u_nice_core.u_mma_top.state)))", 
                                                             "tb_e203_nice.sv", 
                                                             186);
    }
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         187);
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_valid = 0U;
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         191);
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__rsp_ready = 0U;
    VL_WRITEF_NX("[%0t]   Step 2: Deasserted rsp_ready, response should be held\n",0,
                 64,VL_TIME_UNITED_Q(1000),-9);
    while ((1U & (~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid) 
                     | (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid))))) {
        co_await vlSelfRef.__VtrigSched_hcf9bbd92__0.trigger(1U, 
                                                             nullptr, 
                                                             "@([changed] (tb_e203_nice.u_nice_core.u_wbu.csr_buf_rd_valid | tb_e203_nice.u_nice_core.u_wbu.mma_buf_rd_valid))", 
                                                             "tb_e203_nice.sv", 
                                                             196);
    }
    VL_WRITEF_NX("[%0t]   Step 3: Response valid asserted (rsp_valid=%b, rsp_ready=%b)\n",0,
                 64,VL_TIME_UNITED_Q(1000),-9,1,((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid) 
                                                 | (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid)),
                 1,(IData)(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.rsp_ready));
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         201);
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         201);
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         201);
    VL_WRITEF_NX("[%0t]   Step 4: Sending new CSR read while previous response pending\n",0,
                 64,VL_TIME_UNITED_Q(1000),-9);
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_valid = 1U;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_inst = 0x7c8040fbU;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_rs1 = 0U;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_rs2 = 0U;
    while ((1U & (~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_inst)
                      ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_ready)
                      : (0U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state)))))) {
        co_await vlSelfRef.__VtrigSched_h3ada226f__0.trigger(1U, 
                                                             nullptr, 
                                                             "@([changed] (tb_e203_nice.u_nice_core.u_decode_dispatch.is_csr_inst ? tb_e203_nice.u_nice_core.csr_ready : (2'h0 == tb_e203_nice.u_nice_core.u_mma_top.state)))", 
                                                             "tb_e203_nice.sv", 
                                                             208);
    }
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         209);
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_valid = 0U;
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         213);
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__rsp_ready = 1U;
    VL_WRITEF_NX("[%0t]   Step 5: Asserted rsp_ready, completing first response\n",0,
                 64,VL_TIME_UNITED_Q(1000),-9);
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         216);
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__rsp_ready = 0U;
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         218);
    while ((1U & (~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid) 
                     | (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid))))) {
        co_await vlSelfRef.__VtrigSched_hcf9bbd92__0.trigger(1U, 
                                                             nullptr, 
                                                             "@([changed] (tb_e203_nice.u_nice_core.u_wbu.csr_buf_rd_valid | tb_e203_nice.u_nice_core.u_wbu.mma_buf_rd_valid))", 
                                                             "tb_e203_nice.sv", 
                                                             221);
    }
    vlSelfRef.tb_e203_nice__DOT__test_response_backpressure__Vstatic__read_value 
        = ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid)
            ? ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_sel)
                ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_pong
                : vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_ping)
            : ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_sel)
                ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_pong
                : vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_ping));
    if ((0xdeadbeefU != vlSelfRef.tb_e203_nice__DOT__test_response_backpressure__Vstatic__read_value)) {
        VL_WRITEF_NX("[%0t]   ERROR: CSR read mismatch! Expected: 0xdeadbeef, Got: 0x%08x\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,32,
                     vlSelfRef.tb_e203_nice__DOT__test_response_backpressure__Vstatic__read_value);
    } else {
        VL_WRITEF_NX("[%0t]   PASS: CSR[0x7C8] => 0x%08x (correct value read)\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,32,
                     vlSelfRef.tb_e203_nice__DOT__test_response_backpressure__Vstatic__read_value);
    }
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         230);
    VL_WRITEF_NX("[%0t]   Response backpressure test completed\n[%0t] === Test 7: Request Backpressure with Pending Response ===\n",0,
                 64,VL_TIME_UNITED_Q(1000),-9,64,VL_TIME_UNITED_Q(1000),
                 -9);
    VL_WRITEF_NX("[%0t]   Step 1: Write test value to CSR 0x7CA\n",0,
                 64,VL_TIME_UNITED_Q(1000),-9);
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         239);
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_valid = 1U;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_inst = 0x7ca0a07bU;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_rs1 = 0x5a5aa5a5U;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_rs2 = 0U;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__rsp_ready = 1U;
    while ((1U & (~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_inst)
                      ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_ready)
                      : (0U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state)))))) {
        co_await vlSelfRef.__VtrigSched_h3ada226f__0.trigger(1U, 
                                                             nullptr, 
                                                             "@([changed] (tb_e203_nice.u_nice_core.u_decode_dispatch.is_csr_inst ? tb_e203_nice.u_nice_core.csr_ready : (2'h0 == tb_e203_nice.u_nice_core.u_mma_top.state)))", 
                                                             "tb_e203_nice.sv", 
                                                             246);
    }
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         247);
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_valid = 0U;
    while ((1U & (~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid) 
                     | (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid))))) {
        co_await vlSelfRef.__VtrigSched_hcf9bbd92__0.trigger(1U, 
                                                             nullptr, 
                                                             "@([changed] (tb_e203_nice.u_nice_core.u_wbu.csr_buf_rd_valid | tb_e203_nice.u_nice_core.u_wbu.mma_buf_rd_valid))", 
                                                             "tb_e203_nice.sv", 
                                                             250);
    }
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         251);
    VL_WRITEF_NX("[%0t]   Step 2: Send read instruction and hold rsp_ready low\n",0,
                 64,VL_TIME_UNITED_Q(1000),-9);
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__rsp_ready = 0U;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_valid = 1U;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_inst = 0x7ca040fbU;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_rs1 = 0U;
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_rs2 = 0U;
    while ((1U & (~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_inst)
                      ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_ready)
                      : (0U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state)))))) {
        co_await vlSelfRef.__VtrigSched_h3ada226f__0.trigger(1U, 
                                                             nullptr, 
                                                             "@([changed] (tb_e203_nice.u_nice_core.u_decode_dispatch.is_csr_inst ? tb_e203_nice.u_nice_core.csr_ready : (2'h0 == tb_e203_nice.u_nice_core.u_mma_top.state)))", 
                                                             "tb_e203_nice.sv", 
                                                             260);
    }
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         261);
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__req_valid = 0U;
    VL_WRITEF_NX("[%0t]   Step 3: Wait for response with rsp_ready=0\n",0,
                 64,VL_TIME_UNITED_Q(1000),-9);
    while ((1U & (~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid) 
                     | (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid))))) {
        co_await vlSelfRef.__VtrigSched_hcf9bbd92__0.trigger(1U, 
                                                             nullptr, 
                                                             "@([changed] (tb_e203_nice.u_nice_core.u_wbu.csr_buf_rd_valid | tb_e203_nice.u_nice_core.u_wbu.mma_buf_rd_valid))", 
                                                             "tb_e203_nice.sv", 
                                                             265);
    }
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         267);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         267);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         267);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         267);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         267);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         267);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         267);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         267);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         267);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         267);
    if (VL_UNLIKELY((((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid) 
                      | (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid)) 
                     & (~ (IData)(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.rsp_ready))))) {
        VL_WRITEF_NX("[%0t]   PASS: Response held due to backpressure (valid=%b, ready=%b)\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,1,
                     ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid) 
                      | (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid)),
                     1,(IData)(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.rsp_ready));
    }
    VL_WRITEF_NX("[%0t]   Step 4: Release backpressure and verify data\n",0,
                 64,VL_TIME_UNITED_Q(1000),-9);
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         274);
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb__DOT__rsp_ready = 1U;
    while ((1U & (~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid) 
                     | (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid))))) {
        co_await vlSelfRef.__VtrigSched_hcf9bbd92__0.trigger(1U, 
                                                             nullptr, 
                                                             "@([changed] (tb_e203_nice.u_nice_core.u_wbu.csr_buf_rd_valid | tb_e203_nice.u_nice_core.u_wbu.mma_buf_rd_valid))", 
                                                             "tb_e203_nice.sv", 
                                                             277);
    }
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         278);
    while ((1U & (~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid) 
                     | (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid))))) {
        co_await vlSelfRef.__VtrigSched_hcf9bbd92__0.trigger(1U, 
                                                             nullptr, 
                                                             "@([changed] (tb_e203_nice.u_nice_core.u_wbu.csr_buf_rd_valid | tb_e203_nice.u_nice_core.u_wbu.mma_buf_rd_valid))", 
                                                             "tb_e203_nice.sv", 
                                                             279);
    }
    vlSelfRef.tb_e203_nice__DOT__test_request_backpressure__Vstatic__read_value 
        = ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid)
            ? ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_sel)
                ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_pong
                : vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_ping)
            : ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_sel)
                ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_pong
                : vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_ping));
    if ((0x5a5aa5a5U != vlSelfRef.tb_e203_nice__DOT__test_request_backpressure__Vstatic__read_value)) {
        VL_WRITEF_NX("[%0t]   ERROR: CSR read mismatch! Expected: 0x5a5aa5a5, Got: 0x%08x\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,32,
                     vlSelfRef.tb_e203_nice__DOT__test_request_backpressure__Vstatic__read_value);
    } else {
        VL_WRITEF_NX("[%0t]   PASS: CSR[0x7CA] => 0x%08x (correct value read after backpressure)\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,32,
                     vlSelfRef.tb_e203_nice__DOT__test_request_backpressure__Vstatic__read_value);
    }
    co_await vlSelfRef.__VtrigSched_hc83f1028__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_e203_nice.nice_if_inst.cb)", 
                                                         "tb_e203_nice.sv", 
                                                         289);
    VL_WRITEF_NX("[%0t]   Request backpressure test completed\n",0,
                 64,VL_TIME_UNITED_Q(1000),-9);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         106);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         106);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         106);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         106);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         106);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         106);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         106);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         106);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         106);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         106);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         106);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         106);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         106);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         106);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         106);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         106);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         106);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         106);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         106);
    co_await vlSelfRef.__VtrigSched_hef2abcd9__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_e203_nice.clk)", 
                                                         "tb_e203_nice.sv", 
                                                         106);
    VL_WRITEF_NX("[%0t] === All tests completed ===\n",0,
                 64,VL_TIME_UNITED_Q(1000),-9);
    VL_FINISH_MT("tb_e203_nice.sv", 109, "");
}

#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_e203_nice___024root___dump_triggers__act(Vtb_e203_nice___024root* vlSelf);
#endif  // VL_DEBUG

void Vtb_e203_nice___024root___eval_triggers__act(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___eval_triggers__act\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    CData/*0:0*/ __Vtrigcurrexpr_haaedec92__0;
    __Vtrigcurrexpr_haaedec92__0 = 0;
    CData/*0:0*/ __Vtrigcurrexpr_h57ac893f__0;
    __Vtrigcurrexpr_h57ac893f__0 = 0;
    __Vtrigcurrexpr_haaedec92__0 = ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_inst)
                                     ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_ready)
                                     : (0U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state)));
    __Vtrigcurrexpr_h57ac893f__0 = ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid) 
                                    | (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid));
    vlSelfRef.__VactTriggered.set(0U, (((IData)(vlSelfRef.tb_e203_nice__DOT__clk) 
                                        & (~ (IData)(vlSelfRef.__Vtrigprevexpr___TOP__tb_e203_nice__DOT__clk__0))) 
                                       | ((~ (IData)(vlSelfRef.tb_e203_nice__DOT__rst_n)) 
                                          & (IData)(vlSelfRef.__Vtrigprevexpr___TOP__tb_e203_nice__DOT__rst_n__0))));
    vlSelfRef.__VactTriggered.set(1U, vlSelfRef.__VdlySched.awaitingCurrentTime());
    vlSelfRef.__VactTriggered.set(2U, ((IData)(vlSelfRef.tb_e203_nice__DOT__clk) 
                                       & (~ (IData)(vlSelfRef.__Vtrigprevexpr___TOP__tb_e203_nice__DOT__clk__0))));
    vlSelfRef.__VactTriggered.set(3U, vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb.isFired());
    vlSelfRef.__VactTriggered.set(4U, ((IData)(__Vtrigcurrexpr_haaedec92__0) 
                                       != (IData)(vlSelfRef.__Vtrigprevexpr_haaedec92__0)));
    vlSelfRef.__VactTriggered.set(5U, ((IData)(__Vtrigcurrexpr_h57ac893f__0) 
                                       != (IData)(vlSelfRef.__Vtrigprevexpr_h57ac893f__0)));
    vlSelfRef.__Vtrigprevexpr___TOP__tb_e203_nice__DOT__clk__0 
        = vlSelfRef.tb_e203_nice__DOT__clk;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_e203_nice__DOT__rst_n__0 
        = vlSelfRef.tb_e203_nice__DOT__rst_n;
    if (vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb.isFired()) {
        vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb.clearFired();
        vlSymsp->enqueueTriggeredEventForClearing(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.cb);
    }
    vlSelfRef.__Vtrigprevexpr_haaedec92__0 = __Vtrigcurrexpr_haaedec92__0;
    vlSelfRef.__Vtrigprevexpr_h57ac893f__0 = __Vtrigcurrexpr_h57ac893f__0;
    if (VL_UNLIKELY((1U & (~ (IData)(vlSelfRef.__VactDidInit))))) {
        vlSelfRef.__VactDidInit = 1U;
        vlSelfRef.__VactTriggered.set(4U, 1U);
        vlSelfRef.__VactTriggered.set(5U, 1U);
    }
#ifdef VL_DEBUG
    if (VL_UNLIKELY(vlSymsp->_vm_contextp__->debug())) {
        Vtb_e203_nice___024root___dump_triggers__act(vlSelf);
    }
#endif
}

VL_INLINE_OPT void Vtb_e203_nice___024root___act_comb__TOP__0(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___act_comb__TOP__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_hsked 
        = ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid) 
           & (IData)(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.rsp_ready));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_hsked 
        = (((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid) 
            & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid))) 
           & (IData)(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.rsp_ready));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__inst_handshake 
        = ((IData)(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_valid) 
           & (((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_inst)
                ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_ready)
                : (0U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state))) 
              & ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_mat_mult_t) 
                 | (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_inst))));
}

extern const VlUnpacked<CData/*1:0*/, 64> Vtb_e203_nice__ConstPool__TABLE_hb06abf12_0;

VL_INLINE_OPT void Vtb_e203_nice___024root___nba_sequent__TOP__0(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___nba_sequent__TOP__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    CData/*5:0*/ __Vtableidx1;
    __Vtableidx1 = 0;
    CData/*1:0*/ __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state;
    __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state = 0;
    CData/*7:0*/ __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__cycle_cnt;
    __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__cycle_cnt = 0;
    CData/*0:0*/ __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_sel;
    __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_sel = 0;
    CData/*0:0*/ __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_sel;
    __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_sel = 0;
    CData/*0:0*/ __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wr_sel;
    __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wr_sel = 0;
    CData/*0:0*/ __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_sel;
    __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_sel = 0;
    CData/*0:0*/ __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__state;
    __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__state = 0;
    // Body
    __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_sel 
        = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_sel;
    __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_sel 
        = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_sel;
    __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wr_sel 
        = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wr_sel;
    __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_sel 
        = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_sel;
    __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__state 
        = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__state;
    __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__cycle_cnt 
        = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__cycle_cnt;
    __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state 
        = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state;
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_ready = 1U;
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__retire_mem_holdup 
        = ((IData)(vlSelfRef.tb_e203_nice__DOT__rst_n) 
           && ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__state)
                ? ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__state) 
                   && (1U & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__wb_handshake))))
                : (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__calc_start)));
    if (vlSelfRef.tb_e203_nice__DOT__rst_n) {
        if (vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_hsked) {
            if ((1U & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_sel)))) {
                __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_sel = 1U;
                vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_ping 
                    = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_wb_data;
            } else {
                __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_sel = 0U;
            }
            if (vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_sel) {
                vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_pong 
                    = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_wb_data;
            }
        }
        if (vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_hsked) {
            __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_sel 
                = (1U & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_sel)));
        }
        if (vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__wb_handshake) {
            if ((1U & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wr_sel)))) {
                __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wr_sel = 1U;
                vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_ping = 0U;
            } else {
                __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wr_sel = 0U;
            }
            if (vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wr_sel) {
                vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_pong = 0U;
            }
        }
        if (vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_hsked) {
            __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_sel 
                = (1U & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_sel)));
        }
        if (vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__state) {
            if (vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__state) {
                if (vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__wb_handshake) {
                    __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__state = 0U;
                }
            } else {
                __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__state = 0U;
            }
        } else if (vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__calc_start) {
            __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__state = 1U;
        }
        if ((0U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state))) {
            if (vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__calc_start) {
                __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state = 1U;
                __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__cycle_cnt = 0U;
            }
        } else if ((1U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state))) {
            if ((9U <= (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__cycle_cnt))) {
                __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state = 2U;
                __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__cycle_cnt = 0U;
            } else {
                __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__cycle_cnt 
                    = (0xffU & ((IData)(1U) + (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__cycle_cnt)));
            }
        } else if ((2U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state))) {
            if (((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__mma_wb_valid) 
                 & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__mma_wb_ready))) {
                __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state = 0U;
            }
        } else {
            __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state = 0U;
        }
        if (vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_ren) {
            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_rptr 
                = (0x1fU & ((IData)(1U) + (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_rptr)));
            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read 
                = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__fifo_is_read;
            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_len_0start 
                = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__fifo_len;
            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr 
                = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__fifo_addr;
        }
        if (((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_hsked) 
             & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_sel))) {
            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__pong_full = 1U;
        } else if (((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_hsked) 
                    & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_sel))) {
            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__pong_full = 0U;
        }
        if (((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_hsked) 
             & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_sel)))) {
            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__ping_full = 1U;
        } else if (((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_hsked) 
                    & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_sel)))) {
            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__ping_full = 0U;
        }
        if (((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__wb_handshake) 
             & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wr_sel))) {
            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__pong_full = 1U;
        } else if (((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_hsked) 
                    & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_sel))) {
            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__pong_full = 0U;
        }
        if (((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__wb_handshake) 
             & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wr_sel)))) {
            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__ping_full = 1U;
        } else if (((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_hsked) 
                    & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_sel)))) {
            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__ping_full = 0U;
        }
        if ((0U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state_nxt))) {
            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__last_beat_sent = 0U;
        } else if ((1U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state_nxt))) {
            if (((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fire) 
                 & (0U != (3U & vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr_comb)))) {
                vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__last_beat_sent = 0U;
            }
        } else if ((2U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state_nxt))) {
            if (vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fire) {
                vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__last_beat_sent = 1U;
            }
        }
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_burst_cnt 
            = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__burst_cnt_nxt;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_burst_cnt 
            = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_burst_cnt_nxt;
        if (((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_req) 
             & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__is_csr_read)))) {
            if ((1U & (~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr) 
                          >> 0xbU)))) {
                if ((0x400U & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))) {
                    if ((0x200U & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))) {
                        if ((0x100U & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))) {
                            if ((0x80U & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))) {
                                if ((0x40U & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))) {
                                    if ((1U & (~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr) 
                                                  >> 5U)))) {
                                        if ((1U & (~ 
                                                   ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr) 
                                                    >> 4U)))) {
                                            if ((1U 
                                                 & (~ 
                                                    ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr) 
                                                     >> 3U)))) {
                                                if (
                                                    (1U 
                                                     & (~ 
                                                        ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr) 
                                                         >> 2U)))) {
                                                    if (
                                                        (1U 
                                                         & (~ 
                                                            ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr) 
                                                             >> 1U)))) {
                                                        if (
                                                            (1U 
                                                             & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))) {
                                                            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_rhs_base 
                                                                = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_wdata;
                                                        }
                                                        if (
                                                            (1U 
                                                             & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr)))) {
                                                            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_lhs_base 
                                                                = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_wdata;
                                                        }
                                                    }
                                                    if (
                                                        (2U 
                                                         & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))) {
                                                        if (
                                                            (1U 
                                                             & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr)))) {
                                                            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_dst_base 
                                                                = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_wdata;
                                                        }
                                                        if (
                                                            (1U 
                                                             & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))) {
                                                            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_bias_base 
                                                                = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_wdata;
                                                        }
                                                    }
                                                }
                                                if (
                                                    (4U 
                                                     & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))) {
                                                    if (
                                                        (2U 
                                                         & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))) {
                                                        if (
                                                            (1U 
                                                             & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr)))) {
                                                            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_m 
                                                                = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_wdata;
                                                        }
                                                        if (
                                                            (1U 
                                                             & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))) {
                                                            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_dst_row_stride_b 
                                                                = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_wdata;
                                                        }
                                                    }
                                                    if (
                                                        (1U 
                                                         & (~ 
                                                            ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr) 
                                                             >> 1U)))) {
                                                        if (
                                                            (1U 
                                                             & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr)))) {
                                                            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_k 
                                                                = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_wdata;
                                                        }
                                                        if (
                                                            (1U 
                                                             & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))) {
                                                            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_n 
                                                                = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_wdata;
                                                        }
                                                    }
                                                }
                                            }
                                            if ((8U 
                                                 & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))) {
                                                if (
                                                    (1U 
                                                     & (~ 
                                                        ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr) 
                                                         >> 2U)))) {
                                                    if (
                                                        (1U 
                                                         & (~ 
                                                            ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr) 
                                                             >> 1U)))) {
                                                        if (
                                                            (1U 
                                                             & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr)))) {
                                                            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_lhs_row_stride_b 
                                                                = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_wdata;
                                                        }
                                                        if (
                                                            (1U 
                                                             & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))) {
                                                            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_rhs_row_stride_b 
                                                                = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_wdata;
                                                        }
                                                    }
                                                    if (
                                                        (2U 
                                                         & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))) {
                                                        if (
                                                            (1U 
                                                             & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))) {
                                                            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_rhs_zp 
                                                                = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_wdata;
                                                        }
                                                        if (
                                                            (1U 
                                                             & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr)))) {
                                                            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_lhs_zp 
                                                                = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_wdata;
                                                        }
                                                    }
                                                }
                                                if (
                                                    (4U 
                                                     & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))) {
                                                    if (
                                                        (1U 
                                                         & (~ 
                                                            ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr) 
                                                             >> 1U)))) {
                                                        if (
                                                            (1U 
                                                             & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr)))) {
                                                            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_dst_zp 
                                                                = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_wdata;
                                                        }
                                                        if (
                                                            (1U 
                                                             & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))) {
                                                            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_q_mult_pt 
                                                                = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_wdata;
                                                        }
                                                    }
                                                    if (
                                                        (2U 
                                                         & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))) {
                                                        if (
                                                            (1U 
                                                             & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr)))) {
                                                            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_q_shift_pt 
                                                                = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_wdata;
                                                        }
                                                        if (
                                                            (1U 
                                                             & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))) {
                                                            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_act_min 
                                                                = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_wdata;
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                        if ((0x10U 
                                             & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr))) {
                                            if ((1U 
                                                 & (~ 
                                                    ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr) 
                                                     >> 3U)))) {
                                                if (
                                                    (1U 
                                                     & (~ 
                                                        ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr) 
                                                         >> 2U)))) {
                                                    if (
                                                        (1U 
                                                         & (~ 
                                                            ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr) 
                                                             >> 1U)))) {
                                                        if (
                                                            (1U 
                                                             & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr)))) {
                                                            vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_act_max 
                                                                = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_wdata;
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        if (vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fire) {
            if ((1U & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read_comb)))) {
                if ((((1U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state)) 
                      | (3U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state))) 
                     & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__is_last_burst)))) {
                    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wmask_buf = 0U;
                    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wdata_buf = 0U;
                    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wdata_buf_valid = 1U;
                } else if (vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__is_last_burst) {
                    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wmask_buf = 0U;
                    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wdata_buf = 0U;
                    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wdata_buf_valid = 0U;
                }
            }
        }
        if (((IData)(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_rsp_valid) 
             & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read_comb))) {
            if ((1U & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rd_last_burst)))) {
                vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rdata_buf = 0U;
            }
            if (vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rd_last_burst) {
                if (((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rd_last_burst) 
                     | (2U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_state)))) {
                    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rdata_buf_valid = 0U;
                }
            } else {
                vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rdata_buf_valid = 1U;
            }
        }
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__calc_start = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_req = 0U;
        if (vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__inst_handshake) {
            if (vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_mat_mult_t) {
                vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__use_per_channel 
                    = (1U & (vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_rs2 
                             >> 9U));
                vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__dst_base 
                    = vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_rs1;
                vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__cfg_16bits_ia 
                    = (2U == (3U & (vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_rs2 
                                    >> 7U)));
                vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__calc_start = 1U;
            }
            if ((1U & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_mat_mult_t)))) {
                if (vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_wr) {
                    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_wdata 
                        = vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_rs1;
                    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr 
                        = (vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_inst 
                           >> 0x14U);
                    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__is_csr_read = 0U;
                    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_req = 1U;
                } else if (vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_rd) {
                    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_wdata = 0U;
                    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr 
                        = (vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_inst 
                           >> 0x14U);
                    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__is_csr_read = 1U;
                    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_req = 1U;
                }
            }
        }
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state 
            = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state_nxt;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_state 
            = vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_state_nxt;
    } else {
        __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_sel = 0U;
        __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_sel = 0U;
        __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wr_sel = 0U;
        __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_sel = 0U;
        __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__state = 0U;
        __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state = 0U;
        __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__cycle_cnt = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_rptr = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_ping = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_pong = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_ping = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_pong = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__use_per_channel = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__dst_base = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__cfg_16bits_ia = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__pong_full = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__ping_full = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__pong_full = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__ping_full = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__last_beat_sent = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_burst_cnt = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_burst_cnt = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_rhs_base = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_m = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_dst_row_stride_b = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_lhs_row_stride_b = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_rhs_row_stride_b = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_dst_base = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_rhs_zp = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_k = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_dst_zp = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_n = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_lhs_zp = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_bias_base = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_q_shift_pt = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_act_max = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_lhs_base = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_act_min = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_q_mult_pt = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wmask_buf = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wdata_buf = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_len_0start = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wdata_buf_valid = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rdata_buf = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rdata_buf_valid = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__calc_start = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_wdata = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__is_csr_read = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_req = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state = 0U;
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_state = 0U;
    }
    if ((1U & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__rst_n)))) {
        vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_wptr = 0U;
    }
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__cycle_cnt 
        = __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__cycle_cnt;
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state 
        = __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state;
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_sel 
        = __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_sel;
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_sel 
        = __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_sel;
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wr_sel 
        = __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wr_sel;
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_sel 
        = __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_sel;
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__state 
        = __Vdly__tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__state;
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__mma_wb_valid 
        = (2U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state));
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
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid 
        = ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_sel)
            ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__pong_full)
            : (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__ping_full));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__mma_wb_ready 
        = (1U & (~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wr_sel)
                     ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__pong_full)
                     : (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__ping_full))));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid 
        = ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_sel)
            ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__pong_full)
            : (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__ping_full));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rd_last_burst 
        = ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_burst_cnt) 
           == ((0x1fU & ((IData)(1U) + ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_len_0start) 
                                        + (0U != (3U 
                                                  & vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr))))) 
               - (IData)(1U)));
    vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_rsp_valid 
        = ((IData)(vlSelfRef.tb_e203_nice__DOT__rst_n) 
           && (IData)(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_cmd_valid));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__wb_handshake 
        = ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__mma_wb_ready) 
           & (2U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state)));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_hsked 
        = ((~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_sel)
                ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__pong_full)
                : (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__ping_full))) 
           & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_req));
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
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_wb_data 
        = ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__is_csr_read)
            ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_rdata
            : 0U);
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

void Vtb_e203_nice_nice_if___obs_sequent__TOP__tb_e203_nice__DOT__nice_if_inst__0(Vtb_e203_nice_nice_if* vlSelf);

void Vtb_e203_nice___024root___eval_obs(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___eval_obs\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((4ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        Vtb_e203_nice_nice_if___obs_sequent__TOP__tb_e203_nice__DOT__nice_if_inst__0((&vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst));
    }
}

void Vtb_e203_nice_nice_if___react_sequent__TOP__tb_e203_nice__DOT__nice_if_inst__0(Vtb_e203_nice_nice_if* vlSelf);
void Vtb_e203_nice___024root___react_sequent__TOP__0(Vtb_e203_nice___024root* vlSelf);

void Vtb_e203_nice___024root___eval_react(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___eval_react\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((4ULL & vlSelfRef.__VreactTriggered.word(0U))) {
        Vtb_e203_nice_nice_if___react_sequent__TOP__tb_e203_nice__DOT__nice_if_inst__0((&vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst));
        vlSelfRef.__Vm_traceActivity[2U] = 1U;
        Vtb_e203_nice___024root___react_sequent__TOP__0(vlSelf);
    }
    if ((0x3cULL & vlSelfRef.__VreactTriggered.word(0U))) {
        Vtb_e203_nice___024root___act_comb__TOP__0(vlSelf);
    }
}

VL_INLINE_OPT void Vtb_e203_nice___024root___react_sequent__TOP__0(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___react_sequent__TOP__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_mat_mult_t 
        = (IData)((0x200702bU == (0xfe00707fU & vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_inst)));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_wr 
        = (IData)((0x207bU == (0x707fU & vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_inst)));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_rd 
        = (IData)((0x407bU == (0x707fU & vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_inst)));
    vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_inst 
        = ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_wr) 
           | (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_rd));
}
