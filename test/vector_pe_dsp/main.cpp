#include "Vpe_test_top.h"
#include "verilated.h"

#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <random>

static uint32_t expected(unsigned operation, int16_t a, int16_t b, int32_t acc, bool extended = false) {
    switch (operation) {
    case 0: return uint32_t(int64_t(a) * int64_t(b) + int64_t(acc));
    case 1: return uint32_t(int64_t(acc) + int64_t(a));
    case 2: return uint32_t(acc > int32_t(a) ? acc : int32_t(a));
    case 3: return uint32_t(acc < int32_t(a) ? acc : int32_t(a));
    case 4: return uint32_t(int64_t(a) * int64_t(b));
    case 5: return extended ? uint32_t(uint16_t(a)) * uint32_t(uint16_t(b)) : 0;
    case 6: return extended ? uint32_t(int64_t(a) * uint16_t(b)) : 0;
    default: return uint32_t(acc);
    }
}

int main(int argc, char **argv) {
    Verilated::commandArgs(argc, argv);
    Vpe_test_top dut;
    std::mt19937_64 random(0x41d53024d7ULL);
    int16_t saved_a = 0, saved_b = 0;
    int32_t saved_acc = 0;
    bool initialized = false;
    unsigned saved_op = 0;
    uint64_t cycles = 0, comparisons = 0, enabled_cycles = 0, stalled_cycles = 0;
    std::array<uint64_t, 8> operations{};

    auto check = [&]() {
        if (!initialized) return;
        const uint32_t want = expected(saved_op, saved_a, saved_b, saved_acc);
        if (uint32_t(dut.o_result) != want || uint32_t(dut.o_reference) != want) {
            std::fprintf(stderr,
                         "PE mismatch cycle=%llu clock=%u enable=%u op=%u a=%d b=%d acc=%d "
                         "expected=%08x candidate=%08x reference=%08x\n",
                         static_cast<unsigned long long>(cycles), unsigned(dut.clk), unsigned(dut.i_en),
                         unsigned(dut.i_op), int(saved_a), int(saved_b), int(saved_acc), want,
                         uint32_t(dut.o_result), uint32_t(dut.o_reference));
            std::exit(1);
        }
        const uint32_t extended_want = expected(saved_op, saved_a, saved_b, saved_acc, true);
        if (uint32_t(dut.o_extended) != extended_want) {
            std::fprintf(stderr, "Extended PE mismatch saved_op=%u expected=%08x got=%08x\n",
                         saved_op, extended_want, uint32_t(dut.o_extended));
            std::exit(1);
        }
        comparisons += 3;
    };
    auto cycle = [&](bool enable, unsigned operation, int16_t a, int16_t b, int32_t acc) {
        dut.clk = 0;
        dut.i_en = enable;
        dut.i_op = operation;
        dut.i_a = uint16_t(a);
        dut.i_b = uint16_t(b);
        dut.i_acc = uint32_t(acc);
        dut.eval();
        check();
        dut.clk = 1;
        if (enable) {
            saved_op = operation;
            saved_a = a;
            saved_b = b;
            saved_acc = acc;
            initialized = true;
            ++enabled_cycles;
        } else {
            ++stalled_cycles;
        }
        dut.eval();
        check();
        ++cycles;
        ++operations[operation];
    };

    const std::array<int16_t, 11> values_a{{-32768,-32767,-16384,-129,-1,0,1,127,255,16384,32767}};
    const std::array<int16_t, 9> values_b{{-32768,-32767,-12345,-1,0,1,127,16384,32767}};
    const std::array<int32_t, 13> values_acc{{std::numeric_limits<int32_t>::min(),
        std::numeric_limits<int32_t>::min()+1,-1073741824,-32769,-32768,-1,0,1,32767,32768,
        1073741824,std::numeric_limits<int32_t>::max()-1,std::numeric_limits<int32_t>::max()}};
    for (int16_t a : values_a) {
        for (int16_t b : values_b) {
            for (int32_t acc : values_acc) {
                for (unsigned operation = 0; operation < 8; ++operation) {
                    cycle(true, operation, a, b, acc);
                    for (unsigned held_op = 0; held_op < 8; ++held_op)
                        cycle(false, held_op, int16_t(random()), int16_t(random()), int32_t(random()));
                }
            }
        }
    }
    for (unsigned index = 0; index < 250000; ++index) {
        const bool enable = (random() & 3u) != 0u;
        cycle(enable, unsigned(random() & 7u), int16_t(random()), int16_t(random()), int32_t(random()));
    }
    std::printf("VECTOR_PE_DSP_PASS cycles=%llu comparisons=%llu enabled=%llu stalled=%llu\n",
                static_cast<unsigned long long>(cycles), static_cast<unsigned long long>(comparisons),
                static_cast<unsigned long long>(enabled_cycles), static_cast<unsigned long long>(stalled_cycles));
    for (unsigned operation = 0; operation < 8; ++operation) {
        std::printf("OP %u cycles=%llu\n", operation, static_cast<unsigned long long>(operations[operation]));
    }
    dut.final();
    return 0;
}
