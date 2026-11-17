# Unsigned address division

Run `python3 test/run_cpp_rtl.py conv_divider --verilator /path/to/verilator`.
The RTL test checks unsigned quotient and remainder, zero divisors, boundary values,
powers of two, random inputs, requests during an active division, and reset during a transaction.
C++ and generated simulation code run with undefined-behavior checks. Results are written under `build/conv_divider`.
