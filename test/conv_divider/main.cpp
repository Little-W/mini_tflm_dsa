#include "Vconv_udiv32.h"
#include "verilated.h"
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <vector>

static void require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    Vconv_udiv32 dut;
    auto tick = [&]() { dut.clk = 0; dut.eval(); dut.clk = 1; dut.eval(); };
    dut.rst_n = 0; dut.start = 0; dut.dividend = 0; dut.divisor = 0; tick();
    dut.rst_n = 1;
    std::mt19937 rng(0x9f2715);
    std::vector<uint32_t> boundaries{0,1,2,3,15,16,17,31,32,33,127,128,129,
                                   65535,65536,65537,0x7fffffffu,0x80000000u,0xffffffffu};
    unsigned cases = 0, ignored = 0, fast = 0, iterations = 0;
    auto check = [&](uint32_t n, uint32_t d) {
        require(!dut.busy, "New division while busy");
        dut.dividend = n; dut.divisor = d; dut.start = 1; tick();
        const bool immediate = d == 0;
        require(bool(dut.done) == immediate, "Divide-by-zero completion differs");
        unsigned latency = 0;
        while (!dut.done) {
            require(dut.busy && latency < 32, "Invalid divider progress");
            dut.dividend = uint32_t(rng()); dut.divisor = uint32_t(rng());
            dut.start = 1; ++ignored; tick(); ++latency;
        }
        dut.start = 0;
        require(latency == (d == 0 ? 0u : 32u), "Division latency differs");
        require(!dut.busy, "Completed divider remains busy");
        require(dut.quotient == (d ? n / d : 0xffffffffu), "Quotient differs");
        require(dut.remainder == (d ? n % d : n), "Remainder differs");
        require(bool(dut.div_zero) == (d == 0), "Divide-by-zero flag differs");
        ++cases; fast += immediate; iterations += latency;
    };
    try {
        for (uint32_t n : boundaries) for (uint32_t d : boundaries) check(n,d);
        for (unsigned bit = 0; bit < 32; ++bit)
            for (unsigned i = 0; i < 128; ++i) check(uint32_t(rng()), uint32_t(1u << bit));
        for (unsigned i = 0; i < 20000; ++i) check(uint32_t(rng()), uint32_t(rng()));
        for (unsigned i = 0; i < 4096; ++i) check(uint32_t(rng()) & 4095u, (uint32_t(rng()) & 63u) + 1);
        for (unsigned i = 0; i < 8; ++i) {
            dut.start = 1; dut.dividend = 0xffffffffu; dut.divisor = 3; tick();
            for (unsigned t = 0; t <= i; ++t) tick();
            dut.start = 0; dut.rst_n = 0; tick(); dut.rst_n = 1;
            require(!dut.busy && !dut.done, "Reset did not clear active division");
            check(53u + i, 7);
        }
        std::cout << "{\"passed\":true,\"cases\":" << cases << ",\"immediate_cases\":" << fast
                  << ",\"iterative_cycles\":" << iterations << ",\"ignored_busy_requests\":" << ignored
                  << ",\"reset_abort_cases\":8}\n";
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
