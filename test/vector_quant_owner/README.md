# 向量量化控制与组合逻辑级数

本文保存的资源与路径记录使用当次固定源码、RTL 算术属性选择和 740 个 DSP 的总预算，具体源码与配置见随文测量报告。文中的运行命令用于当前工作区，采用普通 RTL 自动映射并生成新的资源与路径报告。

## 当前结构

深度卷积的计算、量化和写回分别保存自己的有效状态。计算完成的像素进入快照存储，量化流水按通道连续接收快照数据，两个结果槽分别保存正在生成和等待写出的像素。池化使用主状态机中的平均值计算与限幅阶段。

`OUTPUT_INIT`、`VECTOR_INIT` 和 `DW_FINISH` 的资格与状态控制字在同一边沿保存。累加器初始化、快照读写和权重预取直接使用这些寄存标志。全部 89 处状态控制字更新共同保存标志，复位、状态保持和错误处理遵守相同优先级，计算延迟与接口握手周期保持一致。

窗口写入使用完整列地址检查和扩展减法的最高借位共同确定有效范围。扩展减法覆盖全部操作数位，保持未知输入的四态算术传播。舍入单元把十六位和三十二位的舍弃位分别按八位分组归并，再合并各级舍弃状态；完整数值、保护位和最近偶数舍入规则保持一致。

## 验证结果

### 可达状态与控制字

`run.py` 从实际展开后的 RTL 保留 `state`、`depthwise`、`spatial`、`global_pool` 和 `load_kind` 五组寄存器，将其他寄存器及存储输出转换为自由输入。首个采样周期执行复位；后续复位、配置、任务开始、完成接收、DMA 和存储返回均不增加输入限制。

以下四组参数的参考实现与当前实现均通过一步归纳证明。证明确认深度卷积只使用其专用状态，并确认量化控制不会进入未使用的状态编码。

| 配置 | TILE | PE_COUNT | BUS_WIDTH | WINDOW_LANES | 共享存储 | 共享量化 |
|---|---:|---:|---:|---:|---:|---:|
| 生产配置 | 16 | 8 | 64 | 8 | 1 | 0 |
| 通用配置 | 16 | 16 | 32 | 4 | 0 | 1 |
| 小容量配置 | 2 | 1 | 32 | 4 | 0 | 0 |
| 大容量配置 | 64 | 16 | 64 | 16 | 0 | 0 |

状态标志检查覆盖全部二值状态编码、六周期任意状态加载与复位，以及 4,096 个四态状态编码。排空条件检查包含共享存储开启与关闭两种配置及 131,072 次四态比较。当前控制字的六种条件状态选择还覆盖 `0`、`1`、`X`、`Z` 四种条件值。

窗口范围检查覆盖五组尺寸参数的全部二值输入，并执行 327,680 次四态比较。舍入检查覆盖 FPGA 与通用实现、输入寄存开启与关闭、中间寄存开启与关闭的八组参数，比较完整 `result` 和 `floor_value`；两个实现分别执行 52,352 个四态样本，每个样本比较四组寄存配置的两个输出。

### 完整引擎回归

| 配置 | 用例 | 输出检查 | 用例执行周期总和 |
|---|---:|---:|---:|
| 生产配置，8 PE、64 位总线、独立量化 | 616 | 170,743 | 3,422,533 |
| 通用配置，16 PE、32 位总线、共享量化 | 616 | 170,743 | 3,711,728 |
| 生产配置，固定等待性能测试 | 40 | 103,743 | 1,071,159 |

三组测试的逐项完整统计与参考实现一致。回归启用 RTL 断言，覆盖操作切换、输出背压、部分尾拍、窗口并发、读写重叠、错误排空及后续任务恢复。生产配置同时检查权重预取地址与内容，以及共享权重写入的寄存阶段。

### 独立模块综合

生产参数下 `vector_engine` 的完整寄存器连接图最长为 **10 级**。资源为 **10,427 个逻辑 LUT、176 个分布式存储 LUT、6,406 个触发器、71 个 DSP48E1 和 9 个 RAMB18E1**，名义 LUT 合计 **10,603**。这些存储和算术资源由普通 RTL 数组及算术表达式推断。

资源统计、源码和测试散列、各项验证摘要保存在 `validation.json`。

## 复现方法

在仓库根目录运行形式与四态检查：

```sh
python test/vector_quant_owner/run.py --out /tmp/vector_quant_owner
python test/vector_window_write_bounds/run.py --out /tmp/vector_window_bounds
python test/vector_round_pipeline/run.py \
  --reference cedf4ed33661a53c8194eca1d484cdc2279d7549 \
  --out /tmp/vector_rounding
```

生产配置回归与性能测试：

```sh
python test/vector_engine/run.py --out /tmp/vector_production \
  --pes 8 --tile 16 --jobs 1 --cache-sets 16 --cache-policy 3 \
  --cache-line-bytes 128 --bus-width 64 --window-lanes 8 \
  --shared-storage --shared-bank-bytes 8192 --shared-bank-count 7 \
  --shared-ia-banks 2 --check-weight-write-stage \
  --rtl-assertions --stable-stimulus --xilinx

python test/vector_engine/run.py --out /tmp/vector_production \
  --pes 8 --tile 16 --jobs 1 --cache-sets 16 --cache-policy 3 \
  --cache-line-bytes 128 --bus-width 64 --window-lanes 8 \
  --shared-storage --shared-bank-bytes 8192 --shared-bank-count 7 \
  --shared-ia-banks 2 --check-weight-write-stage \
  --rtl-assertions --stable-stimulus --xilinx --skip-build --perf
```

通用配置回归与独立综合：

```sh
python test/vector_engine/run.py --out /tmp/vector_generic \
  --pes 16 --tile 16 --jobs 1 --cache-sets 16 --cache-policy 3 \
  --cache-line-bytes 128 --bus-width 32 --window-lanes 4 \
  --shared-quant --rtl-assertions --stable-stimulus
python scripts/fpga/open_fpga_synth.py --out /tmp/vector_synthesis \
  --case-config test/vector_engine/production_synthesis_cases.json --cases vector \
    --max-register-path-cells 10
```

`--source-root` 可指定固定源码目录。形式检查需要 Yosys Slang，四态检查需要 Icarus Verilog，完整引擎回归需要 Verilator；对应工具路径可以通过脚本参数设置。
