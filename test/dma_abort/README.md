# AXI write completion during task abort

Run `python3 test/run_cpp_rtl.py dma_abort` from the repository root.
The test uses Verilator and undefined-behavior sanitization and covers fourteen
aligned/unaligned and 4 KiB page split combinations with missing source data, stalled address
acceptance, stalled write data and partially transmitted ordinary writes.

The scoreboard checks each accepted AW against the complete W burst and B
response. Address and data payloads must remain stable during backpressure.
An already asserted W beat retains its data and byte strobes. Subsequent beats
complete accepted bursts with zero strobes when the producer has stopped.
Every scenario submits another command without resetting the DMA.

The result contains accepted-address and write-beat totals, source hashes,
the executable hash and sanitizer compilation details. Runtime files remain
under `build/dma_abort` or the directory selected with `--out`.

## 读取授予与取消

```sh
python3 test/dma_abort/run_read_arbiter.py --out build/dma_read32 --bus-width 32
python3 test/dma_abort/run_read_arbiter.py --out build/dma_read64 --bus-width 64
```

读取测试对五个请求方检查寄存授予、授予保持与撤回、描述取消和后续恢复。每个已接受的描述保存请求方标签；普通读取最多保留四个在途描述，其中权重请求可以同时占用两个位置。总计数与五个请求方计数在每个时钟边沿进行独立比较。

请求先经过授予寄存器，下一周期可以提交命令。命令暂存位置在交付 DMA 的边沿准备下一次授予，连续命令的最小接收间隔保持为两个周期。测试还检查已完成的旧描述与被取消的暂存描述在同一边沿释放两个位置，并确认取消后可以继续运行。

地址阻塞场景等待实际 `ARVALID`，随后在每个时钟边沿检查 `ARADDR`、`ARLEN`、
`ARSIZE` 和 `ARBURST` 保持有效且稳定。完成与取消的并发场景依据最后一个读取数据拍的
接收资格安排新命令，分别确认旧命令完成和暂存命令取消。两个权重命令的取消检查在
两个 AXI 地址均已完成握手后开始。

`read_handshake_validation.json` 记录 Verilator 5.054、32 位和 64 位 AXI 的实际结果。
两种总线配置各通过 21 个场景、1,069 项检查，包括 15 次描述取消、5 次完成与取消同拍、
5 次授予撤销及四个在途请求位置占满时的接收控制。

可对仲裁器单独执行资源比较：

```sh
python3 test/dma_abort/synthesize_arbiter.py --out build/arbiter_reference --reference-ref aa2ef9a3
python3 test/dma_abort/synthesize_arbiter.py --out build/arbiter_current
```

综合固定为 `SIZE=16`、`DMA_SIZE=64`、`BUS_WIDTH=64` 和 `CACHE_BLOCKS=64`。脚本保留 `axi_dual_block_dma` 的完整参数化端口并将其作为黑盒，统计范围包括仲裁、计数和描述寄存器。结果不包含 DMA 内部的数据通路与缓存。源码副本、映射网表、资源数量和组合路径单元序列均保存到指定目录；逻辑级数用于比较结构，实际频率由器件时序分析确定。

窗口请求使用 `C_WINDOW` 寄存授予。单独综合中的 `window_grant_boundary` 检查五个普通请求输入到窗口 ready 和 DMA 窗口 valid 的组合可达性；DMA 的端口是该项检查的边界。整个 SoC 的组合级数由完整映射网表另行统计。窗口与普通请求的并发、取消和数值检查见 `test/window_dma`。
