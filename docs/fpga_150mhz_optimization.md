# 完整 SoC RTL 与综合检查

## 当前版本

本版本包含 NPU、PicoRV32、256 KiB CPU RAM、AXI 互连和 UART。生产配置采用 16×16 阵列、64 位总线、8 个向量 PE、7 个 8192 字节共享存储块，以及 4096 字节 im2col 缓存。

目标器件为 `xc7a200tfbg484-3`，目标为总 Slice LUT 不超过 50,000、150 MHz 时序通过，以及完整 SoC 最长寄存器间组合路径不超过 14 个组合单元。

生产 RTL 使用可综合算术、布尔运算和数组描述硬件。LUT、BRAM 和 DSP 由综合工具推断；FPGA 门控采用 BUFGCE，通用门控采用低电平锁存使能结构。新增 RTL 注释使用中文。

## 完整 SoC 开源综合

固定源码使用 Yosys 0.71+40、xc7 器件系列和完整 `soc_top` 进行综合。完整连接图统计从时钟控制的存储输出到同步数据或控制输入，包含跨模块路径。

| 项目 | 当前结果 |
| --- | ---: |
| 逻辑 LUT | 67,029 |
| 触发器 | 44,495 |
| DSP | 333 |
| RAMB36 | 99 |
| RAMB18 | 73 |
| 最长寄存器间组合单元数 | 15 |
| 连接图完整性 | 完整 |

当前最长路径为 15 级。两种独立完整 DMA 配置的最长寄存器路径均为 14 级。完整 SoC 使用上表的直接测量结果。

开源工具记录布局前逻辑 LUT 数量；50,000 的目标按 Vivado 总 Slice LUT 检查，包含逻辑、分布式 RAM 和 SRL。当前版本的 Vivado 资源及 150 MHz 布线后时序等待实际测量。完整参数、源码散列和路径结果见 [SoC 测量数据](data/npu_soc_optimization_20261121.json)。

## 已完成验证

| 检查 | 结果 |
| --- | --- |
| PE8 共享存储向量引擎 | 1,031 个场景，308,441 个输出元素通过 |
| PE16 共享量化向量引擎 | 1,031 个场景，308,748 个输出元素通过 |
| 操作数读取完成与任务恢复 | 5 个任务通过，覆盖响应等待、完成背压和同拍故障处理 |
| DMA 中止与恢复 | 16 个事务边界场景及 16 次后续恢复通过 |
| 时钟门控 | 通用分支与官方 BUFGCE 模型分支通过 |

完整生产 NPU 的功能通过状态尚未确认。各模块目录保存当前算术等价、实际控制更新、四态检查与数值回归的结果。上述完整向量及控制回归均使用相同的固定 RTL，详见 [RTL 验证数据](data/npu_rtl_verification_20261121.json)。

## Vivado 运行入口

在仓库根目录执行；已有仓库保留 `picorv32` 子模块，首次克隆后执行 `git submodule update --init picorv32`。

```bash
NPU_CONFIG="$PWD/config/npu_fpga.mk" \
VIVADO_SYNTH_STRATEGY=Flow_AreaOptimized_high \
VIVADO_SYNTH_DIRECTIVE=AreaOptimized_high \
VIVADO_RUN_IMPL=0 VIVADO_JOBS=8 \
vivado -mode batch -source scripts/fpga/vivado_synth_fpga.tcl \
  -tclargs build/vivado_150mhz xc7a200tfbg484-3 16 4 65536 0
```

核心时钟默认 150 MHz。脚本调用 Python 3 记录源码和参数清单，并生成资源及时序摘要。综合报告位于 `build/vivado_150mhz/reports/`。如需布局布线，将 `VIVADO_RUN_IMPL` 设为 `1` 并使用新的工程目录，布线后的报告位于对应 `reports/routed/`。

## 完整连接图复现

```bash
python scripts/fpga/open_fpga_synth.py --cases soc_top \
  --max-register-path-cells 14 --require-register-path-limit \
  --out build/open_soc_150mhz
```

入口检查完整连接图，任一路径超过指定阈值时返回非零状态，同时保留综合及路径报告。
