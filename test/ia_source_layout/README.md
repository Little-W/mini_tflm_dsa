# 生产 DMA 输入激活数据排列

`ia_loader` 和 `ia_loader_cache_mgr` 提供默认关闭的 `p_dma_source_layout` 参数。生产配置为 `SIZE=16`、`DATA_WIDTH=16`、`BUS_WIDTH=64` 时，该参数按 DMA 的实际数据排列减少宽移位选择。

S8 数据的列起点是八的整数倍，S16 每次最多提供前四个有效输入通道。四个输入通道先按列地址的低三位移动，S8 的后四个通道保留在组内高半部，最后按列地址的最高位移动八列。条件选择保留四态数据的逐位传播；写掩码、行边界、写命令寄存和读出周期保持原有定义。

## DMA 输出性质

`test/dma_source_layout/prove.py` 对真实 `axi_dual_block_dma` 和 `axi_linear_block_dma` 证明以下性质，包含复位后的输出无效周期：

- `wr_use_16bits=0` 时，`wr_col_base[2:0]=0`。
- `wr_use_16bits=1` 时，`wr_valid[7:4]=0`。

该证明覆盖 `SIZE=16/64`、`IM2COL_SIZE=16`、`BUS_WIDTH=64`、`DATA_WIDTH=16`，对 im2col、窗口队列和保护器的输出采用任意逐周期取值。证明脚本及结果位于提交 `46c1cbdb`。

## 验证结果

| 检查 | 结果 |
|---|---:|
| cache 状态及公开输出形式比较 | 2,946 位通过 |
| 完整 IA 加载器状态及公开输出形式比较 | 12,186 位通过 |
| 完整 cache 接口逐周期比较 | 200,000 周期、13 个输出、2,600,000 次比较通过 |
| 四态数据排列比较 | 100,002 组、200,004 次比较通过 |

形式比较以已证明的 DMA 输出性质生成输入空间，其他数据、地址、配置、复位和读取控制均可任意变化。接口比较同时检查写命令保持、无效周期输出、所有输入通道、写掩码和读出元数据。四态检查覆盖数据中的 `0/1/X/Z`。

## 模块综合

同一份 RTL 分别关闭和启用 `p_dma_source_layout`，使用生产 cache 参数及原有 xc7 综合流程。

| 项目 | 通用排列 | 生产 DMA 排列 |
|---|---:|---:|
| 逻辑 LUT | 1,560 | 1,341 |
| 分布式存储 LUT | 8 | 8 |
| 寄存器 | 354 | 354 |
| DSP48E1 | 6 | 6 |
| CARRY4 | 22 | 22 |
| 最长组合逻辑级数 | 12 | 11 |
| 寄存器间最长组合逻辑级数 | 10 | 11 |

生产 DMA 排列减少 219 个逻辑 LUT。此表记录模块映射结果；SoC 的物理 LUT 数量和 150 MHz 时序由完整实现报告确定。

## 复现

```bash
source /workspace/scratch/92f7be750f11/toolchain/env.sh
python3 test/dma_source_layout/prove.py --out /tmp/dma_source_layout
python3 test/ia_source_layout/run_formal.py --out /tmp/ia_source_layout_formal
python3 test/ia_source_layout/run_interface.py --out /tmp/ia_source_layout_interface
python3 test/ia_source_layout/run_four_state.py --out /tmp/ia_source_layout_four_state
python3 test/ia_source_layout/prepare_measurement.py --out /tmp/ia_source_layout_synth
python3 scripts/fpga/open_fpga_synth.py \
  --source-root "$PWD" \
  --case-config /tmp/ia_source_layout_synth/cases.json \
  --cases general production --out /tmp/ia_source_layout_synth/native
```

详细参数、源码摘要和运行结果保存在 `measurement.json`。
