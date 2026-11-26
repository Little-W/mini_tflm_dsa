# IA 与部分和帧调度的分组比较

`ia_loader_ctrl` 按相邻两位检查六处定宽加一关系，每六组比较结果独立归并。迭代结束、L2 组切换和权重组宽度选择使用这些结果。普通行与末列行的突发拍数由 `ia_burst_decrement` 分别转换为八位长度字段，列边界只选择已经完成的长度。

`ps_window_scheduler` 将候选归约位置的完整 32 位相等检查分成两个 16 位部分。每个部分保留三位比较分组，完成条件同时用于命令描述和压力恢复资格。

这组修改保持全部状态寄存器、存储容量、接口和时钟周期。所有算术与比较均使用普通 RTL。

## 完整模块验证

参考提交为 `351f3fb63f8d8b36e46c36c7ab539cae475cc8d2`。通用形式验证显式取消 `SYNTHESIS` 和 `XILINX_FPGA`，FPGA 形式验证显式定义两者。

- 完整 IA 控制器覆盖五组尺寸、总线、缓存和紧凑存储配置，完整帧调度器覆盖五组帧容量与复用参数。两种编译模式共通过 20 项无输入限制的时序等价证明，比较 55,018 个状态和输出位，包含存储内容。
- IA 四态仿真覆盖两种存储配置和两种编译模式，共完成 80,016 个周期，在时钟沿前后比较全部公开输出，每种配置均经过五个控制状态。
- 帧调度器四态仿真覆盖四组参数和两种编译模式，共完成 65,536 个周期，包含正常发射、压力暂停、配置变化和未知控制输入。
- 加一关系在 1～64 位范围的十二组位宽下完成 155,648 次四态比较，其中四位操作数穷举全部 65,536 种输入组合。
- 模块头和端口中文注释检查通过。

## 资源与路径

以下结果来自完整模块在相同选项下的布局前映射。名义 LUT 数量包含逻辑 LUT 和 LUTRAM。映射使用 `physical-cost`，最大 LUT 输入数为 8，目标延迟为 6,667 ps，连线代价为 300 ps。

| 完整模块配置 | 参考 LUT | 当前 LUT | 参考最长路径 | 当前最长路径 | 指定路径变化 |
|---|---:|---:|---:|---:|---|
| IA，`COMPACT_S8=0` | 1,536 | 1,496 | 10 | 10 | `w_group_last_idx` 到 `w_cur_r`：10 → 7 |
| IA，`COMPACT_S8=1` | 1,845 | 1,794 | 11 | 10 | `w_group_last_idx` 到 `w_cur_r`：11 → 7 |
| 帧调度器，16 个帧槽 | 1,146 | 1,146 | 10 | 10 | `frame_k` 到 `command_buffer_recoverable`：10 → 8 |

两种 IA 配置分别保留 789、862 个触发器，均使用 3 个自动推断的 DSP，LUTRAM 分别占用 12、20 个名义 LUT 位置。帧调度器保留 916 个触发器、7 个 DSP、2 个 RAMB36 和 56 个名义 LUTRAM 位置。这些资源数量在每组参考与当前实现之间保持一致。

IA 参数为 `SIZE=16`、`DATA_WIDTH=16`、`BUS_WIDTH=64`、`REG_WIDTH=32`、`COUNT_WIDTH=29`、`CACHE_BLOCKS=32` 和 `PS_FRAME_COUNT=16`。帧调度器参数为 `SIZE=16`、`FRAME_COUNT=16`、`MAX_REUSE_TILES=16`。完整参数和指定路径保存在 `measurement.json`，验证结果与源文件摘要保存在 `validation.json`。整机的全部连接路径和资源由完整 SoC 报告提供。

## 复现

```bash
python3 test/storage_group_comparisons/run_formal.py --out build/storage_group_comparisons/formal
python3 test/storage_group_comparisons/run_four_state.py --out build/storage_group_comparisons/four_state
python3 test/storage_group_comparisons/measure.py --out build/storage_group_comparisons/measurement
```

运行环境需要配置 PyYosys、Slang 和 Icarus Verilog。
