// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design internal header
// See Vtb_e203_nice.h for the primary calling header

#ifndef VERILATED_VTB_E203_NICE___024ROOT_H_
#define VERILATED_VTB_E203_NICE___024ROOT_H_  // guard

#include "verilated.h"
#include "verilated_timing.h"
class Vtb_e203_nice_nice_if;


class Vtb_e203_nice__Syms;

class alignas(VL_CACHE_LINE_BYTES) Vtb_e203_nice___024root final : public VerilatedModule {
  public:
    // CELLS
    Vtb_e203_nice_nice_if* __PVT__tb_e203_nice__DOT__nice_if_inst;

    // DESIGN SPECIFIC STATE
    // Anonymous structures to workaround compiler member-count bugs
    struct {
        CData/*0:0*/ tb_e203_nice__DOT__clk;
        CData/*0:0*/ tb_e203_nice__DOT__rst_n;
        CData/*0:0*/ tb_e203_nice__DOT____Vcellout__u_nice_core__nice_icb_cmd_valid;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__calc_start;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__cfg_16bits_ia;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__use_per_channel;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__csr_req;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__is_csr_read;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__csr_ready;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__mma_wb_valid;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__mma_wb_ready;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__retire_mem_holdup;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_mat_mult_t;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_wr;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_rd;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_inst;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__inst_handshake;
        CData/*1:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state;
        CData/*7:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__cycle_cnt;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_ren;
        CData/*4:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_wptr;
        CData/*4:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_rptr;
        CData/*4:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__burst_cycle_1start;
        CData/*4:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_burst_cnt;
        CData/*4:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__burst_cnt_nxt;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__fifo_is_read;
        CData/*3:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__fifo_len;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read;
        CData/*3:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_len_0start;
        CData/*4:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_burst_cnt;
        CData/*4:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_burst_cnt_nxt;
        CData/*3:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wmask_buf;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wdata_buf_valid;
        CData/*3:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wmask_aligned;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rdata_buf_valid;
        CData/*1:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state;
        CData/*1:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state_nxt;
        CData/*1:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_state;
        CData/*1:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_state_nxt;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fire;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__is_last_burst;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rd_last_burst;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__last_beat_sent;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read_comb;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__sa_rsp_ready_comb;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT____VdfgRegularize_hc6488b08_0_5;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__ping_full;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__pong_full;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_sel;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_sel;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_hsked;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_hsked;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__ping_full;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__pong_full;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wr_sel;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_sel;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_hsked;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__state;
        CData/*0:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__wb_handshake;
        CData/*0:0*/ __VdlyVal__tb_e203_nice__DOT__clk__v0;
        CData/*0:0*/ __VdlySet__tb_e203_nice__DOT__clk__v0;
        CData/*0:0*/ __VstlFirstIteration;
    };
    struct {
        CData/*0:0*/ __Vtrigprevexpr___TOP__tb_e203_nice__DOT__clk__0;
        CData/*0:0*/ __Vtrigprevexpr___TOP__tb_e203_nice__DOT__rst_n__0;
        CData/*0:0*/ __Vtrigprevexpr_haaedec92__0;
        CData/*0:0*/ __Vtrigprevexpr_h57ac893f__0;
        CData/*0:0*/ __VactDidInit;
        CData/*0:0*/ __VactContinue;
        CData/*0:0*/ __VnbaContinue;
        CData/*0:0*/ __VobsContinue;
        SData/*11:0*/ tb_e203_nice__DOT__u_nice_core__DOT__csr_addr;
        IData/*31:0*/ tb_e203_nice__DOT__send_csr_read__Vstatic__read_value;
        IData/*31:0*/ tb_e203_nice__DOT__test_response_backpressure__Vstatic__read_value;
        IData/*31:0*/ tb_e203_nice__DOT__test_request_backpressure__Vstatic__read_value;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__dst_base;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__csr_wdata;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__csr_rdata;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__csr_wb_data;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__fifo_addr;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wdata_buf;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wdata_aligned;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rdata_buf;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rdata_aligned;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr_comb;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_lhs_base;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_rhs_base;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_dst_base;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_bias_base;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_k;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_n;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_m;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_dst_row_stride_b;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_lhs_row_stride_b;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_rhs_row_stride_b;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_lhs_zp;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_rhs_zp;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_dst_zp;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_q_mult_pt;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_q_shift_pt;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_act_min;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_act_max;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_ping;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_pong;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_ping;
        IData/*31:0*/ tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_pong;
        IData/*31:0*/ __VactIterCount;
        IData/*31:0*/ __VnbaIterCount;
        IData/*31:0*/ __VobsIterCount;
        VlUnpacked<QData/*36:0*/, 16> tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_mem;
        VlUnpacked<CData/*0:0*/, 3> __Vm_traceActivity;
    };
    VlDelayScheduler __VdlySched;
    VlTriggerScheduler __VtrigSched_hef2abcd9__0;
    VlTriggerScheduler __VtrigSched_hc83f1028__0;
    VlTriggerScheduler __VtrigSched_h3ada226f__0;
    VlTriggerScheduler __VtrigSched_hcf9bbd92__0;
    VlTriggerVec<1> __VstlTriggered;
    VlTriggerVec<6> __VactTriggered;
    VlTriggerVec<6> __VnbaTriggered;
    VlTriggerVec<6> __VobsTriggered;
    VlTriggerVec<6> __VreactTriggered;

    // INTERNAL VARIABLES
    Vtb_e203_nice__Syms* const vlSymsp;

    // CONSTRUCTORS
    Vtb_e203_nice___024root(Vtb_e203_nice__Syms* symsp, const char* v__name);
    ~Vtb_e203_nice___024root();
    VL_UNCOPYABLE(Vtb_e203_nice___024root);

    // INTERNAL METHODS
    void __Vconfigure(bool first);
};


#endif  // guard
