#include "Vtb_compute_core.h"
#include "verilated.h"
#include "verilated_vcd_c.h"
#include <iostream>
#include <string>

vluint64_t tick = 0;

int main(int argc, char **argv)
{
    Verilated::commandArgs(argc, argv);
    Vtb_compute_core *test_top = new Vtb_compute_core;

    // check if trace is enabled
    int trace_en = 0;
    for (int i = 0; i < argc; i++)
    {
        if (strcmp(argv[i], "-t") == 0)
            trace_en = 1;
        if (strcmp(argv[i], "--trace") == 0)
            trace_en = 1;
    }

    if (trace_en)
    {
        std::cout << "Trace is enabled.\n";
    }
    else
    {
        std::cout << "Trace is disabled.\n";
    }

    // enable waveform
    VerilatedVcdC *tfp = new VerilatedVcdC;
    if (trace_en)
    {
        Verilated::traceEverOn(true);
        test_top->trace(tfp, 99);
        tfp->open("wave.vcd");
    }

    test_top->clk = 0;
    test_top->rst_n = 0;
    test_top->eval();
    if (trace_en)
        tfp->dump(tick++);

    // reset for 100 cycles
    for (int i = 0; i < 100; i++)
    {
        if (i % 5 == 0) test_top->clk = !test_top->clk;
        test_top->eval();
        if (trace_en)
            tfp->dump(tick++);
    }

    test_top->rst_n = 1;
    test_top->eval();
    if (trace_en)
        tfp->dump(tick++);

    // run for 50000 cycles
    for (int i = 0; i < 50000; i++)
    {
        if (i % 5 == 0) test_top->clk = !test_top->clk;
        test_top->eval();
        if (trace_en) {
            tfp->dump(tick++);
        }
    }

    if (trace_en)
    {
        tfp->close();
    }
    delete test_top;
    return 0;
}
