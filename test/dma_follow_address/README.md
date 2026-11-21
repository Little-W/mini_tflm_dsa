# 线性 DMA 后续地址检查

`axi_linear_block_dma` 分别准备当前突发的后续地址与下一行的起始地址，再根据剩余拍数选择完整结果。普通首行与合并首行也分别准备地址。地址计算中的突发长度限制、字节偏移和 4 KiB 页边界行为保持一致。

已通过的检查结果、综合统计和源码 SHA-256 保存在 [measurement.json](measurement.json)。

当突发跨度只涉及页内低位时，低地址加法的进位直接决定是否选择页边界地址。恰好到达页边界时，两种地址计算结果相同。其余地址宽度与总线宽度继续使用完整页边界比较。所有状态更新、AXI 通道握手和公开输出周期均保持不变。

## 检查范围

完整模块等价检查复用 `test/dma_byte_layout/run_formal.py`。11 组参数覆盖 32、64、128、1024 位总线，16、17、32 位地址，一个、两个、三个和四个读取上下文，单拍及较短突发限制，以及 `SIZE=64`、`CACHE_BLOCKS=64` 的生产配置。检查不限制外部输入，比较对应状态和全部公开输出。

读取事务检查复用 `test/linear_dma_context/run.py`。固定和随机阻塞分别覆盖 32 位与 64 位总线、一个与四个读取上下文、256 字节突发限制、非整字地址、跨 4 KiB 边界及错误响应后的继续执行。三组配置共完成 1160 条命令、481052 次输出比较和 128523 个周期。

## 独立综合结果

参考提交为 `dde5e7c9836a71f0292d7c69040f8635840e6bad`。两份实现采用相同生产参数：`SIZE=64`、`BUS_WIDTH=64`、`DATA_WIDTH=16`、`REG_WIDTH=32`、`RD_CONTEXT_DEPTH=4`、`DMA_MAX_BYTES=2048`、`CACHE_BLOCKS=64`。

| 测量项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 1740 | 1742 |
| 触发器 | 744 | 740 |
| CARRY4 | 176 | 184 |
| RAMB18 | 1 | 1 |
| DSP48E1 | 1 | 1 |
| 到 `rd_follow_addr` 的最长寄存器间路径 | 14 | 11 |
| 模块内最长寄存器间路径 | 14 | 14 |

综合使用 `synth_xilinx -family xc7 -noiopad -noclkbuf -flatten`，测量依据映射单元间的实际连接。综合器推导存储器、乘法器与进位单元。完整 SoC 的跨模块路径由整机测量检查，150 MHz 时序由器件布局布线报告确认。

## 复现命令

从仓库根目录执行，需要 `pyosys` 和 Verilator。

```bash
python3 test/dma_byte_layout/run_formal.py \
  --reference-ref dde5e7c9 --address-parameters \
  --context-parameters --production-parameters \
  --out /tmp/npu_dma_follow/formal
python3 test/dma_follow_address/prepare_measurement.py \
  --baseline-ref dde5e7c9 --out /tmp/npu_dma_follow/measurement
python3 scripts/fpga/open_fpga_synth.py \
  --source-root /tmp/npu_dma_follow/measurement/inputs/current \
  --case-config /tmp/npu_dma_follow/measurement/cases.json \
  --cases reference current \
  --out /tmp/npu_dma_follow/measurement/synthesis
python3 test/linear_dma_context/run.py \
  --verilator verilator --bus-width 64 --outstanding 4 --contexts 4 \
  --out /tmp/npu_dma_follow/context64
python3 test/linear_dma_context/run.py \
  --verilator verilator --bus-width 32 --outstanding 4 --contexts 4 \
  --out /tmp/npu_dma_follow/context32
python3 test/linear_dma_context/run.py \
  --verilator verilator --bus-width 64 --outstanding 1 --contexts 1 \
  --dma-max-bytes 256 --out /tmp/npu_dma_follow/context1_short
python3 test/dma_follow_address/collect_report.py \
  --formal /tmp/npu_dma_follow/formal \
  --measurement /tmp/npu_dma_follow/measurement \
  --contexts /tmp/npu_dma_follow/context64 /tmp/npu_dma_follow/context32 \
    /tmp/npu_dma_follow/context1_short \
  --out /tmp/npu_dma_follow/measurement.json
```

综合准备入口保存两份实际 RTL 和公共依赖。汇总入口检查源码 SHA-256 与各项结果一致，并保存完整参数、形式比较、事务统计及 `rd_follow_addr` 的实际连接路径。
