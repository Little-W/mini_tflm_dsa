// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design internal header
// See Vmma_controller_if.h for the primary calling header

#ifndef VERILATED_VMMA_CONTROLLER_IF___024ROOT_H_
#define VERILATED_VMMA_CONTROLLER_IF___024ROOT_H_  // guard

#include "verilated.h"
#include "verilated_timing.h"
class Vmma_controller_if_bias_loader_if;
class Vmma_controller_if_compute_core_if;
class Vmma_controller_if_control_if__R20;
class Vmma_controller_if_ia_loader_if;
class Vmma_controller_if_oa_writer_if;
class Vmma_controller_if_requant_if;
class Vmma_controller_if_weight_loader_if;


class Vmma_controller_if__Syms;

class alignas(VL_CACHE_LINE_BYTES) Vmma_controller_if___024root final : public VerilatedModule {
  public:
    // CELLS
    Vmma_controller_if_control_if__R20* __PVT__tb_mma_controller__DOT__ctrl_if;
    Vmma_controller_if_ia_loader_if* __PVT__tb_mma_controller__DOT__ia_if;
    Vmma_controller_if_weight_loader_if* __PVT__tb_mma_controller__DOT__weight_if;
    Vmma_controller_if_bias_loader_if* __PVT__tb_mma_controller__DOT__bias_if;
    Vmma_controller_if_requant_if* __PVT__tb_mma_controller__DOT__quant_if;
    Vmma_controller_if_oa_writer_if* __PVT__tb_mma_controller__DOT__oa_if;
    Vmma_controller_if_compute_core_if* __PVT__tb_mma_controller__DOT__comp_if;

    // DESIGN SPECIFIC STATE
    // Anonymous structures to workaround compiler member-count bugs
    struct {
        CData/*0:0*/ tb_mma_controller__DOT__clk;
        CData/*0:0*/ tb_mma_controller__DOT__rst_n;
        CData/*0:0*/ tb_mma_controller__DOT____Vcellout__dut__write_oa_granted;
        CData/*0:0*/ tb_mma_controller__DOT____Vcellout__dut__load_quant_granted;
        CData/*0:0*/ tb_mma_controller__DOT____Vcellout__dut__load_bias_granted;
        CData/*0:0*/ tb_mma_controller__DOT____Vcellout__dut__send_weight_trigger;
        CData/*0:0*/ tb_mma_controller__DOT____Vcellout__dut__load_weight_granted;
        CData/*0:0*/ tb_mma_controller__DOT____Vcellout__dut__send_ia_trigger;
        CData/*0:0*/ tb_mma_controller__DOT____Vcellout__dut__load_ia_granted;
        CData/*0:0*/ tb_mma_controller__DOT____Vcellout__dut__use_16bits;
        CData/*0:0*/ tb_mma_controller__DOT____Vcellout__dut__init_cfg_oa;
        CData/*0:0*/ tb_mma_controller__DOT____Vcellout__dut__init_cfg_requant;
        CData/*0:0*/ tb_mma_controller__DOT____Vcellout__dut__init_cfg_bias;
        CData/*0:0*/ tb_mma_controller__DOT____Vcellout__dut__init_cfg_weight;
        CData/*0:0*/ tb_mma_controller__DOT____Vcellout__dut__init_cfg_ia;
        CData/*2:0*/ tb_mma_controller__DOT____Vcellout__dut__icb_sel;
        CData/*0:0*/ tb_mma_controller__DOT__dut__DOT__use_per_channel;
        CData/*0:0*/ tb_mma_controller__DOT__dut__DOT__wb_ready;
        CData/*1:0*/ tb_mma_controller__DOT__dut__DOT__err_code;
        CData/*3:0*/ tb_mma_controller__DOT__dut__DOT__current_state;
        CData/*3:0*/ tb_mma_controller__DOT__dut__DOT__next_state;
        CData/*0:0*/ tb_mma_controller__DOT__dut__DOT__cfg_16bits_ia_reg;
        CData/*0:0*/ tb_mma_controller__DOT__dut__DOT__config_error;
        CData/*1:0*/ tb_mma_controller__DOT__dut__DOT__error_type;
        CData/*2:0*/ tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__current_master;
        CData/*0:0*/ tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__bus_busy;
        CData/*0:0*/ tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__bus_idle;
        CData/*0:0*/ tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__current_done;
        CData/*2:0*/ tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__unnamedblk1__DOT__next_device;
        CData/*0:0*/ __Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__10__Vfuncout;
        CData/*0:0*/ __Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__10__ptr_error;
        CData/*0:0*/ __Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__10__dim_error;
        CData/*0:0*/ __Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__10__stride_error;
        CData/*0:0*/ __Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__10__quant_error;
        CData/*0:0*/ __VstlFirstIteration;
        CData/*0:0*/ __Vtrigprevexpr___TOP__tb_mma_controller__DOT__clk__0;
        CData/*0:0*/ __Vtrigprevexpr___TOP__tb_mma_controller__DOT__rst_n__0;
        CData/*0:0*/ __Vtrigprevexpr_he004758a__0;
        CData/*0:0*/ __Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__load_weight_granted__0;
        CData/*0:0*/ __Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__send_weight_trigger__0;
        CData/*0:0*/ __Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__load_ia_granted__0;
        CData/*0:0*/ __Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__send_ia_trigger__0;
        CData/*0:0*/ __Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__load_bias_granted__0;
        CData/*0:0*/ __Vtrigprevexpr___TOP__tb_mma_controller__DOT__comp_if__tile_calc_over__0;
        CData/*0:0*/ __Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__load_quant_granted__0;
        CData/*0:0*/ __Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__write_oa_granted__0;
        CData/*0:0*/ __Vtrigprevexpr___TOP__tb_mma_controller__DOT__ia_if__ia_sending_done__0;
        CData/*0:0*/ __Vtrigprevexpr___TOP__tb_mma_controller__DOT__oa_if__oa_calc_over__0;
        CData/*0:0*/ __Vtrigprevexpr_hbb0eeb4f__0;
        CData/*0:0*/ __VactDidInit;
        CData/*0:0*/ __VactContinue;
        CData/*0:0*/ __VnbaContinue;
        IData/*31:0*/ tb_mma_controller__DOT____Vcellout__dut__tile_count;
        IData/*31:0*/ tb_mma_controller__DOT__dut__DOT__lhs_base;
        IData/*31:0*/ tb_mma_controller__DOT__dut__DOT__rhs_base;
        IData/*31:0*/ tb_mma_controller__DOT__dut__DOT__dst_base;
        IData/*31:0*/ tb_mma_controller__DOT__dut__DOT__bias_base;
        IData/*31:0*/ tb_mma_controller__DOT__dut__DOT__q_mult_pt;
        IData/*31:0*/ tb_mma_controller__DOT__dut__DOT__q_shift_pt;
        IData/*31:0*/ tb_mma_controller__DOT__dut__DOT__k;
        IData/*31:0*/ tb_mma_controller__DOT__dut__DOT__n;
        IData/*31:0*/ tb_mma_controller__DOT__dut__DOT__m;
        IData/*31:0*/ tb_mma_controller__DOT__dut__DOT__lhs_row_stride_b;
        IData/*31:0*/ tb_mma_controller__DOT__dut__DOT__dst_row_stride_b;
    };
    struct {
        IData/*31:0*/ tb_mma_controller__DOT__dut__DOT__rhs_row_stride_b;
        IData/*31:0*/ __VactIterCount;
        IData/*31:0*/ __VnbaIterCount;
        VlUnpacked<CData/*2:0*/, 4> tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue;
        VlUnpacked<CData/*2:0*/, 4> tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__next_priority_queue;
        VlUnpacked<CData/*0:0*/, 2> __Vm_traceActivity;
    };
    VlDelayScheduler __VdlySched;
    VlTriggerScheduler __VtrigSched_hdac58424__0;
    VlTriggerScheduler __VtrigSched_h42ebdd83__0;
    VlTriggerScheduler __VtrigSched_h38e6f19c__0;
    VlTriggerScheduler __VtrigSched_h742f9b30__0;
    VlTriggerScheduler __VtrigSched_h9cd046e4__0;
    VlTriggerScheduler __VtrigSched_h4c63e026__0;
    VlTriggerScheduler __VtrigSched_h66f97190__0;
    VlTriggerScheduler __VtrigSched_haadd1735__0;
    VlTriggerScheduler __VtrigSched_h47b3a967__0;
    VlTriggerScheduler __VtrigSched_hb997b169__0;
    VlTriggerScheduler __VtrigSched_hf7995922__0;
    VlTriggerScheduler __VtrigSched_h41abe5e7__0;
    VlTriggerScheduler __VtrigSched_h8b2b3151__0;
    VlTriggerScheduler __VtrigSched_h90096cfe__0;
    VlTriggerScheduler __VtrigSched_ha535fff4__0;
    VlTriggerScheduler __VtrigSched_h4a02e0d9__0;
    VlTriggerScheduler __VtrigSched_h28ec1f55__0;
    VlTriggerScheduler __VtrigSched_h4463a28d__0;
    VlForkSync __Vfork_1__sync;
    VlTriggerScheduler __VtrigSched_hcbbc710c__0;
    VlTriggerScheduler __VtrigSched_h2ab923a2__0;
    VlTriggerVec<1> __VstlTriggered;
    VlTriggerVec<22> __VactTriggered;
    VlTriggerVec<22> __VnbaTriggered;
    VlTriggerVec<22> __VobsTriggered;

    // INTERNAL VARIABLES
    Vmma_controller_if__Syms* const vlSymsp;

    // CONSTRUCTORS
    Vmma_controller_if___024root(Vmma_controller_if__Syms* symsp, const char* v__name);
    ~Vmma_controller_if___024root();
    VL_UNCOPYABLE(Vmma_controller_if___024root);

    // INTERNAL METHODS
    void __Vconfigure(bool first);
};


#endif  // guard
