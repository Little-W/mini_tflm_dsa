// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Model implementation (design independent parts)

#include "Vmma_controller_if__pch.h"
#include "verilated_vcd_c.h"

//============================================================
// Constructors

Vmma_controller_if::Vmma_controller_if(VerilatedContext* _vcontextp__, const char* _vcname__)
    : VerilatedModel{*_vcontextp__}
    , vlSymsp{new Vmma_controller_if__Syms(contextp(), _vcname__, this)}
    , __PVT__tb_mma_controller__DOT__ctrl_if{vlSymsp->TOP.__PVT__tb_mma_controller__DOT__ctrl_if}
    , __PVT__tb_mma_controller__DOT__ia_if{vlSymsp->TOP.__PVT__tb_mma_controller__DOT__ia_if}
    , __PVT__tb_mma_controller__DOT__weight_if{vlSymsp->TOP.__PVT__tb_mma_controller__DOT__weight_if}
    , __PVT__tb_mma_controller__DOT__bias_if{vlSymsp->TOP.__PVT__tb_mma_controller__DOT__bias_if}
    , __PVT__tb_mma_controller__DOT__quant_if{vlSymsp->TOP.__PVT__tb_mma_controller__DOT__quant_if}
    , __PVT__tb_mma_controller__DOT__oa_if{vlSymsp->TOP.__PVT__tb_mma_controller__DOT__oa_if}
    , __PVT__tb_mma_controller__DOT__comp_if{vlSymsp->TOP.__PVT__tb_mma_controller__DOT__comp_if}
    , rootp{&(vlSymsp->TOP)}
{
    // Register model with the context
    contextp()->addModel(this);
    contextp()->traceBaseModelCbAdd(
        [this](VerilatedTraceBaseC* tfp, int levels, int options) { traceBaseModel(tfp, levels, options); });
}

Vmma_controller_if::Vmma_controller_if(const char* _vcname__)
    : Vmma_controller_if(Verilated::threadContextp(), _vcname__)
{
}

//============================================================
// Destructor

Vmma_controller_if::~Vmma_controller_if() {
    delete vlSymsp;
}

//============================================================
// Evaluation function

#ifdef VL_DEBUG
void Vmma_controller_if___024root___eval_debug_assertions(Vmma_controller_if___024root* vlSelf);
#endif  // VL_DEBUG
void Vmma_controller_if___024root___eval_static(Vmma_controller_if___024root* vlSelf);
void Vmma_controller_if___024root___eval_initial(Vmma_controller_if___024root* vlSelf);
void Vmma_controller_if___024root___eval_settle(Vmma_controller_if___024root* vlSelf);
void Vmma_controller_if___024root___eval(Vmma_controller_if___024root* vlSelf);

void Vmma_controller_if::eval_step() {
    VL_DEBUG_IF(VL_DBG_MSGF("+++++TOP Evaluate Vmma_controller_if::eval_step\n"); );
#ifdef VL_DEBUG
    // Debug assertions
    Vmma_controller_if___024root___eval_debug_assertions(&(vlSymsp->TOP));
#endif  // VL_DEBUG
    vlSymsp->__Vm_activity = true;
    vlSymsp->clearTriggeredEvents();
    vlSymsp->__Vm_deleter.deleteAll();
    if (VL_UNLIKELY(!vlSymsp->__Vm_didInit)) {
        vlSymsp->__Vm_didInit = true;
        VL_DEBUG_IF(VL_DBG_MSGF("+ Initial\n"););
        Vmma_controller_if___024root___eval_static(&(vlSymsp->TOP));
        Vmma_controller_if___024root___eval_initial(&(vlSymsp->TOP));
        Vmma_controller_if___024root___eval_settle(&(vlSymsp->TOP));
    }
    VL_DEBUG_IF(VL_DBG_MSGF("+ Eval\n"););
    Vmma_controller_if___024root___eval(&(vlSymsp->TOP));
    // Evaluate cleanup
    Verilated::endOfEval(vlSymsp->__Vm_evalMsgQp);
}

void Vmma_controller_if::eval_end_step() {
    VL_DEBUG_IF(VL_DBG_MSGF("+eval_end_step Vmma_controller_if::eval_end_step\n"); );
#ifdef VM_TRACE
    // Tracing
    if (VL_UNLIKELY(vlSymsp->__Vm_dumping)) vlSymsp->_traceDump();
#endif  // VM_TRACE
}

//============================================================
// Events and timing
bool Vmma_controller_if::eventsPending() { return !vlSymsp->TOP.__VdlySched.empty(); }

uint64_t Vmma_controller_if::nextTimeSlot() { return vlSymsp->TOP.__VdlySched.nextTimeSlot(); }

//============================================================
// Utilities

const char* Vmma_controller_if::name() const {
    return vlSymsp->name();
}

//============================================================
// Invoke final blocks

void Vmma_controller_if___024root___eval_final(Vmma_controller_if___024root* vlSelf);

VL_ATTR_COLD void Vmma_controller_if::final() {
    Vmma_controller_if___024root___eval_final(&(vlSymsp->TOP));
}

//============================================================
// Implementations of abstract methods from VerilatedModel

const char* Vmma_controller_if::hierName() const { return vlSymsp->name(); }
const char* Vmma_controller_if::modelName() const { return "Vmma_controller_if"; }
unsigned Vmma_controller_if::threads() const { return 1; }
void Vmma_controller_if::prepareClone() const { contextp()->prepareClone(); }
void Vmma_controller_if::atClone() const {
    contextp()->threadPoolpOnClone();
}
std::unique_ptr<VerilatedTraceConfig> Vmma_controller_if::traceConfig() const {
    return std::unique_ptr<VerilatedTraceConfig>{new VerilatedTraceConfig{false, false, false}};
};

//============================================================
// Trace configuration

void Vmma_controller_if___024root__trace_decl_types(VerilatedVcd* tracep);

void Vmma_controller_if___024root__trace_init_top(Vmma_controller_if___024root* vlSelf, VerilatedVcd* tracep);

VL_ATTR_COLD static void trace_init(void* voidSelf, VerilatedVcd* tracep, uint32_t code) {
    // Callback from tracep->open()
    Vmma_controller_if___024root* const __restrict vlSelf VL_ATTR_UNUSED = static_cast<Vmma_controller_if___024root*>(voidSelf);
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    if (!vlSymsp->_vm_contextp__->calcUnusedSigs()) {
        VL_FATAL_MT(__FILE__, __LINE__, __FILE__,
            "Turning on wave traces requires Verilated::traceEverOn(true) call before time 0.");
    }
    vlSymsp->__Vm_baseCode = code;
    if (strlen(vlSymsp->name())) tracep->pushPrefix(std::string{vlSymsp->name()}, VerilatedTracePrefixType::SCOPE_MODULE);
    Vmma_controller_if___024root__trace_decl_types(tracep);
    Vmma_controller_if___024root__trace_init_top(vlSelf, tracep);
    if (strlen(vlSymsp->name())) tracep->popPrefix();
}

VL_ATTR_COLD void Vmma_controller_if___024root__trace_register(Vmma_controller_if___024root* vlSelf, VerilatedVcd* tracep);

VL_ATTR_COLD void Vmma_controller_if::traceBaseModel(VerilatedTraceBaseC* tfp, int levels, int options) {
    (void)levels; (void)options;
    VerilatedVcdC* const stfp = dynamic_cast<VerilatedVcdC*>(tfp);
    if (VL_UNLIKELY(!stfp)) {
        vl_fatal(__FILE__, __LINE__, __FILE__,"'Vmma_controller_if::trace()' called on non-VerilatedVcdC object;"
            " use --trace-fst with VerilatedFst object, and --trace with VerilatedVcd object");
    }
    stfp->spTrace()->addModel(this);
    stfp->spTrace()->addInitCb(&trace_init, &(vlSymsp->TOP));
    Vmma_controller_if___024root__trace_register(&(vlSymsp->TOP), stfp->spTrace());
}
