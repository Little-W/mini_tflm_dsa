// SPDX-License-Identifier: Apache-2.0
#include "Vtb_model_benchmark.h"
#include "verilated.h"
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <memory>

int main(int argc, char **argv) {
    auto context = std::make_unique<VerilatedContext>();
    context->commandArgs(argc, argv);
    auto top = std::make_unique<Vtb_model_benchmark>(context.get());
    top->clk = 0;
    top->rst_n = 0;
    top->eval();
    std::uint64_t cycles = 0;
    const auto started = std::chrono::steady_clock::now();
    while (!context->gotFinish()) {
        top->rst_n = cycles >= 8;
        top->clk = 0;
        context->timeInc(5);
        top->eval();
        top->clk = 1;
        context->timeInc(5);
        top->eval();
        ++cycles;
        if (cycles % 5000000 == 0) {
            const double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now()-started).count();
            std::printf("SOC_NETWORK_HEARTBEAT cycles=%llu pc=%08x progress=%08x host_seconds=%.3f simulated_cycles_per_second=%.0f\n",
                        static_cast<unsigned long long>(cycles),top->pc,top->progress,seconds,cycles/seconds);
            std::fflush(stdout);
        }
    }
    top->final();
    return 0;
}
