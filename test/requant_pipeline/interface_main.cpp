#include "Vrequant_interface_top.h"
#include "verilated.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>

int main(int argc, char **argv) {
    VerilatedContext context;
    context.commandArgs(argc, argv);
    Vrequant_interface_top dut(&context);
    uint32_t rng = 0x274129a3;
    uint64_t cycles = 0, vectors = 0, dma_commands = 0, dma_beats = 0;
    auto random = [&]() { rng ^= rng << 13; rng ^= rng >> 17; rng ^= rng << 5; return rng; };
    auto check = [&]() {
        if (dut.mismatch) {
            std::cerr << "cycle=" << cycles << " mismatch=" << std::hex << dut.mismatch << '\n';
            throw std::runtime_error("Output interface differs");
        }
    };
    auto tick = [&]() {
        dut.clk = 0; dut.eval(); context.timeInc(1); check();
        dut.clk = 1; dut.eval(); context.timeInc(1); check();
        ++cycles;
        vectors += dut.out_valid;
    };
    try {
        dut.rst_n = 0; dut.init_cfg = 0; dut.in_valid = 0;
        dut.in_tile_done = 0; dut.load_quant_granted = 0; dut.dma_raw_valid = 0;
        tick(); tick(); dut.rst_n = 1;
        const std::array<uint32_t, 8> shifts = {0, 30, 31, uint32_t(-31), uint32_t(-32), uint32_t(-63), 0x80000000, 0x7fffffff};
        for (unsigned scenario = 0; scenario < 256; ++scenario) {
            dut.cfg_per_channel = scenario & 1;
            dut.cfg_dataflow_mode = (scenario >> 1) & 1;
            dut.cfg_s16 = (scenario >> 2) & 1;
            dut.activation_min_in = dut.cfg_s16 ? uint32_t(-32768) : uint32_t(-128);
            dut.activation_max_in = dut.cfg_s16 ? 32767 : 127;
            dut.dst_offset_in = scenario % 9 == 0 ? 0x80000000 : random();
            dut.multiplier_in = dut.cfg_per_channel ? 0x10000 : random();
            dut.shift_in = dut.cfg_per_channel ? 0x20000 : shifts[scenario % shifts.size()];
            dut.k = 1 + random() % 96; dut.m = 1 + random() % 67;
            dut.ia_reuse_num_in = 1U << (scenario % 6);
            dut.init_cfg = 1; dut.in_valid = 0; dut.in_tile_done = 0;
            dut.load_quant_granted = 0; dut.dma_raw_valid = 0; tick(); dut.init_cfg = 0;
            unsigned response_left = 0, response_delay = 0, rows = 0;
            for (unsigned cycle = 0; cycle < 2048; ++cycle) {
                dut.load_quant_granted = (random() & 3) != 0;
                dut.in_valid = dut.quant_params_valid && ((random() & 3) != 0);
                dut.in_tile_done = dut.in_valid && (++rows % 16 == 0);
                for (unsigned lane = 0; lane < 16; ++lane) dut.in_vec_s32[lane] = random();
                dut.dma_raw_data = random();
                if (TEST_BUS_WIDTH == 64) dut.dma_raw_data |= uint64_t(random()) << 32;
                dut.dma_raw_valid = response_left && !response_delay && ((random() & 3) != 0);
                if (response_delay) --response_delay;
                dut.clk = 0; dut.eval(); check();
                if (dut.dma_start) {
                    if (response_left) throw std::runtime_error("Overlapping parameter commands");
                    response_left = unsigned(dut.dma_burst_len_m1) + 1;
                    response_delay = 1 + random() % 7;
                    ++dma_commands;
                }
                if (dut.dma_raw_valid) { --response_left; ++dma_beats; }
                tick();
                if (cycle == 1023 && scenario % 13 == 0) {
                    dut.rst_n = 0; dut.in_valid = 0; dut.dma_raw_valid = 0;
                    dut.load_quant_granted = 0; tick(); dut.rst_n = 1;
                    response_left = 0; response_delay = 0;
                }
            }
            dut.in_valid = 0; dut.in_tile_done = 0; dut.dma_raw_valid = 0;
            dut.load_quant_granted = 0;
            for (unsigned drain = 0; drain < 16; ++drain) tick();
        }
        if (vectors < 10000 || dma_commands < 100 || dma_beats < 500) throw std::runtime_error("Insufficient exercised transactions");
        std::cout << "{\"passed\":true,\"bus_width\":" << TEST_BUS_WIDTH
                  << ",\"scenarios\":256,\"cycles\":" << cycles
                  << ",\"vectors\":" << vectors << ",\"dma_commands\":" << dma_commands
                  << ",\"dma_beats\":" << dma_beats << "}\n";
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n'; return 1;
    }
    dut.final();
    return 0;
}
