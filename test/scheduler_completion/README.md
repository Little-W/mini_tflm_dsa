# 调度器完成阶段控制验证

`ps_window_scheduler.sv` 在 `COMPLETE` 阶段保存任务状态，完成通知被接收后将 `phase` 更新为 `IDLE`。`done_ready` 只参与阶段寄存器的更新条件。其他任务寄存器在该阶段保持原值。

配置观测字段随 `NPU_SIM_ASSERT` 展开；尺寸比较和条件表达式使用显式无符号扩展。当前源码摘要为 `e6415790fb56eb05f6f291298cf56d69d5774937f94fb439e60faa3a702584a7`，已完成下述全部状态、四态和 975 个任务验证。

## 逐周期正确性

生产配置为 `SIZE=16`、`FRAME_COUNT=16`、`MAX_REUSE_TILES=32`。验证首先证明复位状态满足控制不变量，再对任意外部输入证明不变量的一步归纳关系。其中，活动命令及已缓冲命令都要求调度器处于允许处理命令的阶段，因此 `COMPLETE` 阶段不能处理命令。

随后对参考版本和当前版本建立全部寄存器状态的对应关系，在该不变量成立时，检查复位、所有公开输出和每个寄存器的下一状态。对应关系覆盖 2,289 个状态位，分为 18 组完成 SAT 证明。该方法使用实际 RTL 与全部公共状态，外部输入保持自由。

四态比较运行完整模块，检查公开输出和活动命令状态。独立数值模型检查调度顺序、帧复用、提前完成及存储容量限制。

| 检查项目 | 完成数量 | 结果 |
| --- | ---: | --- |
| 复位与无界归纳不变量 | 生产参数 1 组 | 通过 |
| 下一状态与公开输出 SAT | 2,289 个状态位，18 组 | 通过 |
| 四态公开输出比较 | 82,060 次 | 通过 |
| 含未知值的控制周期 | 28,624 个 | 通过 |
| 活动命令状态检查 | 17,838 次 | 通过 |
| 独立数值模型 | 975 个任务、182,426 条命令 | 通过 |
| 存储容量预留检查 | 141,121 次 | 通过 |
| 存储分组检查 | 1,085,772 次 | 通过 |

数值模型的 C++ 编译单元全部启用 UBSan，遇到未定义行为时立即终止运行。

## 独立模块综合

测量模块保存 `done_ready` 和 `command_pressure` 输入，并保留所有公开输出。参考版本和当前版本采用相同参数、综合定义和 DSP 分配设置。资源统计为布局前的名义 LUT 数，组合级数来自映射后的寄存器间路径图。

此表的完成阶段控制源码摘要为 `f2d8ea7c4b0206604aa1396e6fe7909c71c122085f6183bf75d51e3a4f790823`；当前源码的整机测量使用对应的完整 RTL 快照。

| 项目 | 参考版本 `ef0dc75` | 当前版本 |
| --- | ---: | ---: |
| 逻辑 LUT | 1,152 | 1,155 |
| 分布式存储 LUT | 56 | 56 |
| LUT 合计 | 1,208 | 1,211 |
| 触发器，含两个测量输入寄存器 | 918 | 918 |
| DSP | 13 | 13 |
| RAMB36 | 2 | 2 |
| 模块最长寄存器间组合级数 | 9 | 9 |
| `done_ready` 到寄存器的最长级数 | 6 | 2 |
| `command_pressure` 到寄存器的最长级数 | 5 | 3 |
| `opened` 到寄存器的最长级数 | 9 | 9 |

当前 `done_ready` 路径终点仅涉及阶段寄存器，映射后以 `ready` 和 `done_valid` 别名显示。完整 SoC 的资源和时序由整机综合与实现结果单独记录。

## 执行命令

在仓库根目录执行形式验证及逐周期比较：

```bash
python3 test/scheduler_completion/run_formal.py \
  --out build/scheduler_completion/formal

python3 test/scheduler_command_outputs/run_four_state.py \
  --source-root . \
  --reference-root build/scheduler_completion/formal/reference \
  --profiles 16:16:32 --modes XILINX_FPGA \
  --out build/scheduler_completion/four_state

python3 test/ps_compression/run_window_scheduler.py \
  --out build/scheduler_completion/numeric
```

形式验证生成参考源码后，可执行相同配置的独立综合和路径统计：

```bash
python3 scripts/fpga/open_fpga_synth.py \
  --case-config test/scheduler_completion/synthesis_cases.json \
  --cases reference current \
  --out build/scheduler_completion/synthesis/native \
python3 test/scheduler_completion/collect_paths.py \
  --native build/scheduler_completion/synthesis/native \
  --out build/scheduler_completion/synthesis/path_comparison.json
```

`validation.json` 保存本次验证的源码摘要、检查数量、资源与路径统计。
