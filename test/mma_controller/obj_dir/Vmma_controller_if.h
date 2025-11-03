// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Primary model header
//
// This header should be included by all source files instantiating the design.
// The class here is then constructed to instantiate the design.
// See the Verilator manual for examples.

#ifndef VERILATED_VMMA_CONTROLLER_IF_H_
#define VERILATED_VMMA_CONTROLLER_IF_H_  // guard

#include "verilated.h"

class Vmma_controller_if__Syms;
class Vmma_controller_if___024root;
class VerilatedVcdC;
class Vmma_controller_if_bias_loader_if;
class Vmma_controller_if_compute_core_if;
class Vmma_controller_if_control_if__R20;
class Vmma_controller_if_ia_loader_if;
class Vmma_controller_if_oa_writer_if;
class Vmma_controller_if_requant_if;
class Vmma_controller_if_weight_loader_if;


// This class is the main interface to the Verilated model
class alignas(VL_CACHE_LINE_BYTES) Vmma_controller_if VL_NOT_FINAL : public VerilatedModel {
  private:
    // Symbol table holding complete model state (owned by this class)
    Vmma_controller_if__Syms* const vlSymsp;

  public:

    // CONSTEXPR CAPABILITIES
    // Verilated with --trace?
    static constexpr bool traceCapable = true;

    // PORTS
    // The application code writes and reads these signals to
    // propagate new values into/out from the Verilated model.

    // CELLS
    // Public to allow access to /* verilator public */ items.
    // Otherwise the application code can consider these internals.
    Vmma_controller_if_control_if__R20* const __PVT__tb_mma_controller__DOT__ctrl_if;
    Vmma_controller_if_ia_loader_if* const __PVT__tb_mma_controller__DOT__ia_if;
    Vmma_controller_if_weight_loader_if* const __PVT__tb_mma_controller__DOT__weight_if;
    Vmma_controller_if_bias_loader_if* const __PVT__tb_mma_controller__DOT__bias_if;
    Vmma_controller_if_requant_if* const __PVT__tb_mma_controller__DOT__quant_if;
    Vmma_controller_if_oa_writer_if* const __PVT__tb_mma_controller__DOT__oa_if;
    Vmma_controller_if_compute_core_if* const __PVT__tb_mma_controller__DOT__comp_if;

    // Root instance pointer to allow access to model internals,
    // including inlined /* verilator public_flat_* */ items.
    Vmma_controller_if___024root* const rootp;

    // CONSTRUCTORS
    /// Construct the model; called by application code
    /// If contextp is null, then the model will use the default global context
    /// If name is "", then makes a wrapper with a
    /// single model invisible with respect to DPI scope names.
    explicit Vmma_controller_if(VerilatedContext* contextp, const char* name = "TOP");
    explicit Vmma_controller_if(const char* name = "TOP");
    /// Destroy the model; called (often implicitly) by application code
    virtual ~Vmma_controller_if();
  private:
    VL_UNCOPYABLE(Vmma_controller_if);  ///< Copying not allowed

  public:
    // API METHODS
    /// Evaluate the model.  Application must call when inputs change.
    void eval() { eval_step(); eval_end_step(); }
    /// Evaluate when calling multiple units/models per time step.
    void eval_step();
    /// Evaluate at end of a timestep for tracing, when using eval_step().
    /// Application must call after all eval() and before time changes.
    void eval_end_step();
    /// Simulation complete, run final blocks.  Application must call on completion.
    void final();
    /// Are there scheduled events to handle?
    bool eventsPending();
    /// Returns time at next time slot. Aborts if !eventsPending()
    uint64_t nextTimeSlot();
    /// Trace signals in the model; called by application code
    void trace(VerilatedTraceBaseC* tfp, int levels, int options = 0) { contextp()->trace(tfp, levels, options); }
    /// Retrieve name of this model instance (as passed to constructor).
    const char* name() const;

    // Abstract methods from VerilatedModel
    const char* hierName() const override final;
    const char* modelName() const override final;
    unsigned threads() const override final;
    /// Prepare for cloning the model at the process level (e.g. fork in Linux)
    /// Release necessary resources. Called before cloning.
    void prepareClone() const;
    /// Re-init after cloning the model at the process level (e.g. fork in Linux)
    /// Re-allocate necessary resources. Called after cloning.
    void atClone() const;
    std::unique_ptr<VerilatedTraceConfig> traceConfig() const override final;
  private:
    // Internal functions - trace registration
    void traceBaseModel(VerilatedTraceBaseC* tfp, int levels, int options);
};

#endif  // guard
