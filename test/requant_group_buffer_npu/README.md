# 完整 NPU 的量化分组缓冲器 ASIC 结构检查

`run.py` 调用目标仓库的 `scripts/asic/prepare_dc_sources.py`，根据实际 DC 文件列表生成源文件副本，再使用 Yosys 的 Slang 前端展开完整 `npu_top`。SRAM 使用 `RAMTP128X16` 和 `RAMTP1024X16` 的端口黑盒声明；其他 NPU 模块均参与实际层次展开。

## 生产配置

| 配置项 | 数值 |
|---|---:|
| 计算阵列 | 16 × 16 |
| AXI 数据宽度 | 64 位 |
| 共享存储银行 | 7 × 8192 字节 |
| IA_CACHE_BLOCKS | 4 |
| PS_FRAME_COUNT | 16 |
| IM2COL_CACHE_BYTES | 4096 |
| 向量 PE 数量 | 8 |
| 读、写 outstanding 数量 | 各 4 |

编译定义包括 `SYNTHESIS`、`ASIC_SYNTHESIS`、`ASIC_SRAM`，以及生产配置使用的 `GEMPACT_PS_COMPRESS`、`GEMMORA_PS_POOL_BYTES=49152` 和 `GEMMORA_PS_FORCE_RAW`。共享存储定义保证实际 IA 复用容量和量化分组缓冲容量参与展开。

## 检查内容

- 按真实 DC 文件列表保存源文件和头文件副本，记录每份文件的 SHA-256；检查结束后再次确认源文件内容。
- 调用保存的 `prepare_dc_sources.py`，保留它生成的 `sources.f` 和 `transformations.json`，并按 DC 读取流程追加 `smic40_sram_1r1w.sv`。
- 使用 `read_slang --keep-hierarchy`、`hierarchy -check`、`proc`、`opt_clean`、`memory_collect` 和 `check -assert` 检查完整 NPU 的层次及连接。
- 定位实际 `u_vec_requant` 内的 `requant_group_buffer`，逐个统计 132 个 `RAMTP128X16`；核对 4 个深度分组各含 33 个宽度切片。
- 核对输入、输出的 16 个 32 位通道、513 位存储字宽、9 位地址、10 位行计数，以及 SRAM 宏端口尺寸。
- 检查该缓冲器子层次中推断存储单元和 `regfile` 数量均为 0，控制状态及深度选择寄存器合计为 41 位。
- 检查 256 个 `ws_systolic_cell`、8 个 `vector_pe`、完整共享存储及向量引擎的实例数量。

检查脚本保留存储单元，不执行 `memory_map` 或工艺映射。`measurement.json` 记录当前完整 NPU 的结构检查结果。ASIC 面积及静态时序需要使用 Design Compiler 和对应工艺库测量；本检查使用 Yosys 0.71 的 Slang 前端。

## 执行方法

在可导入 `pyosys` 且支持 `read_slang` 的 Python 环境中执行：

```bash
python3 test/requant_group_buffer_npu/run.py \
  --source-root /path/to/mini_tflm_dsa \
  --out /tmp/requant_group_buffer_npu
```

省略 `--source-root` 时，检查脚本所在仓库。输出包括源文件副本、DC 准备结果、展开脚本、展开日志、压缩网表及 `summary.json`。`--keep-netlist` 可保留未压缩网表。

## 当前结果

| 项目 | 实际值 |
|---|---:|
| 分组缓冲器逻辑容量 | 513 × 512 = 262656 位 |
| 分组缓冲器 SRAM 宏 | 132 × RAMTP128X16 |
| 分组缓冲器宏物理容量 | 270336 位，33792 字节 |
| 分组缓冲器推断存储单元 | 0 |
| 分组缓冲器 regfile 实例 | 0 |
| 分组缓冲器控制及深度选择寄存器 | 41 位 |
| 计算 PE | 256 |
| 向量 PE | 8 |
| 完整 NPU 的 RAMTP128X16 | 372 |
| 完整 NPU 的 RAMTP1024X16 | 16 |

存储行为检查由 `test/requant_group_buffer_memory/` 执行；本目录检查完整 NPU 中的实际集成结构。
