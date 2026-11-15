# DMA page-boundary regression

Run from the repository root:

```sh
python3 test/dma_page_guard/run.py \
  --out build/dma_page_guard \
  --verilator verilator
```

The regression uses the production read and write guards. The read guard keeps
page-local GEMM AR/R traffic on its direct path and waits for outstanding logical
responses before splitting a crossing request. Conv and DW allocation checks
remain controlled by their job configuration. The write guard tracks accepted
addresses, outstanding data bursts and outstanding responses separately. It
splits crossing bursts into page-local segments and returns one response for the
original DMA command.

The standalone test submits 192 reads and 192 writes, including 256-beat bursts,
four outstanding logical requests, random channel delays, write data preceding
its address, partial byte strobes, and read/write response errors. It checks
every output byte, request ordering, original RLAST, segment WLAST and combined
BRESP. Page-local address traffic is checked for direct forwarding.

The complete NPU test executes five GEMM jobs in sequence: a crossing read/write
case, an injected RRESP error, a successful recovery job, an injected BRESP error,
and a second successful recovery job. Error completions must report `ERR=3` and
remain stable until accepted. Recovery jobs run without resetting the NPU.
All memory bytes are compared with the software result, including bytes outside
the output allocation. The AXI memory model checks 4 KiB boundaries for both AR
and AW and validates every physical WLAST.

The result directory contains build logs, execution logs, generated input and
expected memory images, and `summary.json`. `--guard-only` selects the standalone
read/write tests. The existing allocation-specific regression is available as
`python3 test/conv_guard/run.py`.
