# Simulation observers

Performance measurement and testbench checks reside in this directory. Observers
read hardware state through `bind` connections or hierarchical references. They
have no connections that drive functional hardware state.

- `conv_windowed_cache_observer.sv` records demand acceptance, lookup results,
  transferred bytes and prefetch use. Prefetch ownership flags and the count of
  unused resident prefetches exist only in this observer.
- `conv_window_queue_observer.sv` records request and response overlap and the
  maximum number of outstanding descriptors.
- `vector_engine_observer.sv` and `ps_window_scheduler_observer.sv` record
  execution states, commands and capacity pressure.
- `npu_top_observer.sv` and `npu_controller_observer.sv` record task cycles and
  execution utilization.
- The SoC observers record CPU, AXI and software progress events.

Use `sources.py:with_observers` when constructing a simulator source list. It
selects observers for the module definitions present in that list. The complete
NPU VCS environment uses `veri/flist/npu_observers.f`. The behavioral SoC memory
model is in `test/models/soc_axi_ram.sv`; hardware builds use `rtl/soc/soc_axi_ram.sv`.

An example observation is
`dut.u_cache.g_window.u_window.tb_observer.stat_prefetch_unused`. The value is the
number of valid prefetched lines that have not yet served a demand access. The
observer computes it from simulation state; no hardware adder tree is required.

Hardware sources contain functional state and arithmetic required by the
implemented protocol. Optional hardware invariants use `NPU_SIM_ASSERT` and
`initial` simulation processes. Performance counters, scoreboard state,
utilization calculations, and compatibility aliases belong to the testbench.
The diagnostic register addresses `0x0a0`–`0x0ac`, `0x0bc`–`0x0c4` and
`0x128`–`0x130` are reserved and read zero. Functional status, capabilities and
memory configuration remain available through their documented registers.

Run the source separation check with:

```sh
make check-rtl-observers
```
