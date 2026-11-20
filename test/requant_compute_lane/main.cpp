#include "Vrequant_compute_lane.h"
#include "verilated.h"

#include <array>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <random>

struct Result {
    bool valid = false;
    uint8_t s8 = 0;
    uint16_t s16 = 0;
};

static int64_t signed32(uint32_t value) {
    return value < 0x80000000U ? int64_t(value) : int64_t(value) - 0x100000000LL;
}

static Result reference(const Vrequant_compute_lane &dut) {
    Result result;
    result.valid = dut.i_valid;
    if (!dut.i_valid || !dut.i_lane_enable) return result;
    const __int128 product = __int128(signed32(dut.i_value)) * signed32(dut.i_multiplier);
    __int128 quotient = 0;
    bool increment = false;
    if (dut.i_amount < 64) {
        const __int128 divisor = __int128(1) << dut.i_amount;
        quotient = product / divisor;
        __int128 remainder = product % divisor;
        if (remainder < 0) {
            --quotient;
            remainder += divisor;
        }
        increment = dut.i_amount != 0 &&
            (remainder * 2 > divisor || (remainder * 2 == divisor && (quotient % 2) != 0));
        if (quotient > 8589934591LL) quotient = 8589934591LL;
        if (quotient < -8589934592LL) quotient = -8589934592LL;
    }
    const __int128 rounded = quotient + int(increment) +
        (dut.i_s16 ? 0 : signed32(dut.i_dst_offset));
    const int64_t minimum = signed32(dut.i_activation_min);
    const int64_t maximum = signed32(dut.i_activation_max);
    if (rounded < minimum) {
        result.s8 = uint8_t(minimum);
        result.s16 = uint16_t(minimum);
    } else if (rounded > maximum) {
        result.s8 = uint8_t(maximum);
        result.s16 = uint16_t(maximum);
    } else {
        result.s8 = uint8_t(rounded > 127 ? 127 : rounded < -128 ? -128 : int64_t(rounded));
        result.s16 = uint16_t(rounded > 32767 ? 32767 : rounded < -32768 ? -32768 : int64_t(rounded));
    }
    return result;
}

int main(int argc, char **argv) {
    Verilated::commandArgs(argc, argv);
    Vrequant_compute_lane dut;
    std::array<Result, 12> pipeline{};
    std::mt19937_64 rng(0x74917531ce205699ULL);
    uint64_t cycles = 0, outputs = 0, holds = 0, clears = 0, resets = 0, disabled_lanes = 0;
    uint64_t directed = 0, random = 0, clear_during_hold = 0;
    auto step = [&]() {
        dut.clk = 0;
        dut.eval();
        if (!dut.rst_n || dut.i_clear) {
            pipeline = {};
            if (!dut.rst_n) ++resets;
            else {
                ++clears;
                if (!dut.i_en) ++clear_during_hold;
            }
        } else if (dut.i_en) {
            for (int stage = 11; stage > 0; --stage) pipeline[stage] = pipeline[stage - 1];
            pipeline[0] = reference(dut);
            if (dut.i_valid && !dut.i_lane_enable) ++disabled_lanes;
        } else {
            ++holds;
        }
        dut.clk = 1;
        dut.eval();
        ++cycles;
        const Result expected = pipeline[11];
        if (bool(dut.o_valid) != expected.valid || dut.o_s8 != expected.s8 || dut.o_s16 != expected.s16) {
            std::cerr << "Output comparison failed at cycle " << cycles
                      << " actual=" << unsigned(dut.o_valid) << "," << unsigned(dut.o_s8)
                      << "," << unsigned(dut.o_s16) << " expected=" << expected.valid
                      << "," << unsigned(expected.s8) << "," << unsigned(expected.s16) << '\n';
            std::exit(1);
        }
        if (dut.i_en && dut.rst_n && !dut.i_clear && expected.valid) ++outputs;
        dut.clk = 0;
        dut.eval();
    };
    auto drain = [&]() {
        dut.rst_n = 1;
        dut.i_clear = 0;
        dut.i_en = 1;
        dut.i_valid = 0;
        for (int count = 0; count < 12; ++count) step();
    };
    const std::array<uint32_t, 16> values = {
        0, 1, 2, 3, 0xffffffffU, 0xfffffffeU, 0x80000000U, 0x7fffffffU,
        0x00008000U, 0xffff8000U, 0x00010001U, 0xffff0001U,
        0x40000000U, 0xc0000000U, 0x55555555U, 0xaaaaaaaaU
    };
    const std::array<std::array<uint32_t, 3>, 8> configs = {{
        {0, 0x80000000U, 0x7fffffffU}, {0x80000000U, 0x80000000U, 0x7fffffffU},
        {0x7fffffffU, 0x80000000U, 0x7fffffffU}, {127, uint32_t(-128), 127},
        {uint32_t(-32768), uint32_t(-32768), 32767}, {3, 17, uint32_t(-17)},
        {uint32_t(-3), 0, 0}, {1, uint32_t(-100), 100}
    }};
    dut.rst_n = 0;
    dut.i_en = 0;
    dut.i_clear = 0;
    dut.i_valid = 0;
    step();
    dut.rst_n = 1;
    for (unsigned mode = 0; mode < 2; ++mode) {
        for (const auto &cfg : configs) {
            drain();
            dut.i_s16 = mode;
            dut.i_dst_offset = cfg[0];
            dut.i_activation_min = cfg[1];
            dut.i_activation_max = cfg[2];
            for (unsigned amount = 0; amount < 128; ++amount) {
                for (auto value : values) {
                    for (auto multiplier : values) {
                        dut.i_en = 1;
                        dut.i_valid = 1;
                        dut.i_lane_enable = 1;
                        dut.i_value = value;
                        dut.i_multiplier = multiplier;
                        dut.i_amount = amount;
                        step();
                        ++directed;
                        if ((directed & 63U) == 0U) {
                            dut.i_en = 0;
                            dut.i_value = uint32_t(rng());
                            dut.i_multiplier = uint32_t(rng());
                            dut.i_amount = uint8_t(rng() & 127U);
                            step();
                        }
                    }
                }
            }
        }
    }
    for (unsigned group = 0; group < 1024; ++group) {
        dut.i_clear = 1;
        dut.i_en = rng() & 1U;
        step();
        dut.i_clear = 0;
        dut.i_s16 = group & 1U;
        dut.i_dst_offset = uint32_t(rng());
        dut.i_activation_min = uint32_t(rng());
        dut.i_activation_max = uint32_t(rng());
        for (unsigned item = 0; item < 512; ++item) {
            dut.rst_n = (rng() & 1023U) != 0;
            dut.i_clear = (rng() & 255U) == 0;
            dut.i_en = (rng() & 7U) != 0;
            dut.i_valid = (rng() & 3U) != 0;
            dut.i_lane_enable = (rng() & 7U) != 0;
            dut.i_value = uint32_t(rng());
            dut.i_multiplier = uint32_t(rng());
            dut.i_amount = uint8_t(rng() & 127U);
            step();
            ++random;
        }
    }
    drain();
    std::cout << "REQUANT_LANE_PASS cycles=" << cycles << " outputs=" << outputs
              << " directed=" << directed << " random=" << random << " holds=" << holds
              << " clears=" << clears << " resets=" << resets << " disabled_lanes=" << disabled_lanes
              << " clear_during_hold=" << clear_during_hold << " latency=12\n";
    dut.final();
    return 0;
}
