# 完整 NPU 的 ASIC 存储结构检查

`run.py` 调用目标仓库的 `scripts/asic/prepare_dc_sources.py`，根据实际 DC 文件列表保存源文件副本，再使用 Yosys 的 Slang 前端展开完整 `npu_top`。SRAM 使用 `RAMTP128X16` 和 `RAMTP1024X16` 的端口声明，其余 NPU 模块均参与层次展开和连接检查。

## 生产配置与容量推导

| 配置项 | 数值 |
| --- | ---: |
| 计算阵列 | 16×16 |
| AXI 数据宽度 | 64 位 |
| 共享存储 | 7×8192 B |
| IA_CACHE_BLOCKS | 4 |
| PS_FRAME_COUNT | 16 |
| IM2COL_CACHE_BYTES | 4096 |
| 向量 PE 数量 | 16 |
| 读、写 outstanding 数量 | 各 4 |
| IA_COMPACT_ENABLE 默认值 | 0 |

生产配置使用两个 IA 共享存储 bank，一个 16×16×16 位分块占 512 B，因此 `IA_MAX_CACHE_BLOCKS=2×8192/512=32`。IA 压缩开启时，槽位数按生产 RTL 的公式增加为 64；关闭时保持为 32。量化分组行数由 `SIZE×max(1,IA_SLOT_BLOCKS/2)` 计算。

| IA_COMPACT_ENABLE | IA_SLOT_BLOCKS | 最大 IA 复用数量 | 分组行数 | 地址宽度 | 行计数宽度 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 32 | 16 | 256 | 8 | 9 |
| 1 | 64 | 32 | 512 | 9 | 10 |

编译定义包括 `SYNTHESIS`、`ASIC_SYNTHESIS`、`ASIC_SRAM`、`GEMPACT_PS_COMPRESS`、`GEMMORA_PS_POOL_BYTES=49152` 和 `GEMMORA_PS_FORCE_RAW`。`--ia-compact-enable` 始终显式传递给 `npu_top`。

## 当前存储实现

| 存储 | IA 压缩 | 逻辑容量 | RTL 存储形状 | ASIC 资源 | 容量利用率 |
| --- | ---: | ---: | --- | --- | ---: |
| Kernel 列存储 | 0、1 | 1536 B | 16 个 48×16 | 寄存器数组 | 100% |
| Bias | 0 | 2048 B | 256×64，按字节更新 | 8 个 128×16 宏 | 100% |
| Bias | 1 | 4096 B | 512×64，按字节更新 | 4 个 1024×16 宏 | 50% |
| 量化移位参数 | 0 | 224 B | 两个 128×7 | 寄存器数组 | 100% |
| 量化移位参数 | 1 | 448 B | 两个 128×14，每字保存两项 | 2 个 128×16 宏 | 87.5% |
| 量化分组缓冲 | 0 | 16,416 B | 256×513 | 66 个 128×16 宏 | 97.159% |
| 量化分组缓冲 | 1 | 32,832 B | 512×513 | 33 个 1024×16 宏 | 48.580% |

Bias 保持 64 位读写字宽，公共 `regfile` 将全部字节的写入掩码共同连接到 SRAM 的逐位写使能。移位参数根据静态存储深度选择每字一项或两项，同一模块实例承担两种几何配置。

默认分组缓冲使用两个深度分组，每组包含 33 个 16 位宽度切片。物理容量为 16,896 B，逻辑容量为 16,416 B，位宽填充合计 480 B。队列地址、计数、输出有效位及宏读取分组选择位合计为 36 个寄存器位。512 行配置的相应控制状态合计为 40 位。

## 严格检查内容

- 保存真实 DC 文件列表、RTL、头文件和准备程序，记录 SHA-256，运行结束后再次确认输入内容。
- 保留准备程序生成的 `sources.f` 和 `transformations.json`，按 DC 流程追加实际 SRAM 封装。
- 执行 `read_slang --keep-hierarchy`、`hierarchy -check`、`proc`、`opt_clean`、`memory_collect` 和 `check -assert`。
- 检查完整 NPU 包含 256 个 `ws_systolic_cell`、16 个 `vector_pe`、一个共享存储模块和一个完整量化分组缓冲。
- 检查 AXI 数据端口为 64 位、写掩码为 8 位；两种 SRAM 的端口方向及宽度须与实际宏接口一致。
- 逐个核对分组缓冲 SRAM 的深度分组编号、宽度切片编号、数量、实际逻辑行数、513 位字宽及控制状态宽度。
- 分组缓冲内推断存储单元和 `regfile` 数量均须为 0；其他逻辑模块不得以未展开模块参与检查。
- 分别核对 Kernel、Bias 和移位参数存储的公共端口、写入单位、逻辑深度、实际数组尺寸、宏数量、容量及填充位数。

`--implementation-profile` 明确选择需要检查的实现。`820c` 对应参考提交的 SRAM 选择和存储组织；`current` 对应当前 64 位 Bias 整字掩码和移位参数静态深度选择。每种配置均有固定要求，脚本不接受任意存储几何。

## 执行方法

```bash
python3 test/requant_group_buffer_npu/run.py \
  --source-root /path/to/current_source \
  --implementation-profile current --ia-compact-enable 0 \
  --out /tmp/npu_current_ia0

python3 test/requant_group_buffer_npu/run.py \
  --source-root /path/to/current_source \
  --implementation-profile current --ia-compact-enable 1 \
  --out /tmp/npu_current_ia1

python3 test/requant_group_buffer_npu/run.py \
  --source-root /path/to/source_820c \
  --implementation-profile 820c --ia-compact-enable 0 \
  --out /tmp/npu_820c_ia0
```

省略 `--source-root` 时使用脚本所在仓库，省略 IA 参数时使用 0。参考源码的 IA 开启配置以 `--ia-compact-enable 1` 运行。输出包含源文件副本、DC 准备结果、展开脚本、日志、压缩网表及 `summary.json`。`--keep-netlist` 可保留未压缩网表。

`measurement.json` 保存参考提交与当前源码的四项结果，完整 NPU 的宏数量如下：

| 源码 | IA_COMPACT_ENABLE | 128×16 宏 | 1024×16 宏 |
| --- | ---: | ---: | ---: |
| `820c2b18` | 0 | 52 | 97 |
| `820c2b18` | 1 | 40 | 105 |
| 当前源码 | 0 | 110 | 64 |
| 当前源码 | 1 | 42 | 101 |

SRAM 封装的边界功能检查覆盖默认深度 128、256、384、385、1100，以及显式指定宏深度的两项配置，共 9105 次比较。分组缓冲功能与控制检查由 `test/requant_group_buffer_memory/` 执行，13 种配置通过数据比较及控制属性检查，功能测试共读取 39,642 行，比较 5,188,506 个消费数据位。

本检查记录存储结构和容量。实际 ASIC 总面积及 150 MHz 时序由 `scripts/asic/compare_memory_area.py` 使用相同工艺库和约束进行原生 DC 比较。
