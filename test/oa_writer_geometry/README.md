# 输出写回的行数比较与验证

`oa_writer` 根据矩阵尺寸、复用数量、WS/IS 模式和合并写回配置生成 DMA 描述符。模块保留既有配置接收、请求准备、DMA 启动、数据传输和完成状态，公开接口与各寄存器逐周期行为一致。

## 行数选择

初始行数选择比较 `k` 与 `co_initial_limit`，下一组行数选择比较 `co_next_rows_remaining_q` 与 `co_rows_limit`。两处共用 `unsigned_compare` 模块，按完整 `REG_WIDTH` 位宽比较。各字节分组并行产生次序信息，再组合得到完整操作数的大小关系。

两个比较结果分别选择已经准备的行数和分块数量。计数器截断、地址回绕、九位行数和 WS/IS 模式选择沿用对应信号的原有位宽。输入或保存状态出现未知值时，关系运算和条件选择保留四态传播语义。

`co_initial_rows`、`co_current_rows`、`co_next_rows_prepared` 及相应分块数量继续在既有时钟边沿更新。流水线阶段和握手时序保持一致。

## 验证结果

参考实现为提交 `7ff66a59` 中的 `oa_writer.sv`。验证覆盖全部 21 项公开输出以及 77 个非阻塞赋值状态目标。

| 检查 | 配置与运行数量 | 结果 |
|---|---|---|
| 综合分支形式证明 | 11 组参数，包含生产 `16:64:29:32` | 全部通过 |
| 仿真分支形式证明 | `4:32:4`、`16:64:29`、`16:64:1` | 全部通过 |
| 四态公开输出比较 | 4 组合法通道配置，4096 场景、102780 周期、205556 次严格比较 | 全部通过 |
| 逐周期数值比较 | 8 组配置，4096 场景、4178136 周期 | 全部通过 |

形式证明比较完整模块，逐项观察全部状态目标，不限制配置值或握手输入。数值回归包含 128375 条 DMA 命令、19793 次合并组启动、2214 次完成和 1429 次运行期间重新配置，并开启 C++ 未定义行为检查。四态回归覆盖维度、复用数量、步长、模式、数据和字节掩码中的 X/Z 值。

## 局部映射

映射参数为 `VLEN=16`、`BUS_WIDTH=64`、`COUNT_WIDTH=29`、`REG_WIDTH=32`，采用相同的 xc7 自动算术映射配置。

| 指标 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 1380 | 1428 |
| 触发器位 | 944 | 944 |
| 自动推断的 DSP48E1 | 2 | 2 |
| CARRY4 | 150 | 140 |
| 包含模块输入的最长组合路径级数 | 12 | 10 |
| 内部寄存器间最长组合路径级数 | 10 | 10 |

这些数值覆盖独立写回模块的布局前映射。完整 SoC 中任务配置寄存器至写回行数寄存器的路径需要结合其上下游逻辑分析，150 MHz 时序由完整设计的综合及布局布线报告确定。

## 运行方法

需要 Python 3、提供 `read_slang` 的 `pyosys`、Verilator、Icarus Verilog 和 C++ 编译器。

```sh
python3 test/oa_writer_geometry/run_compare_formal.py --synthesis \
  --out build/oa_writer_geometry/formal_synthesis
python3 test/oa_writer_geometry/run_compare_formal.py \
  --profiles 4:32:4 16:64:29 16:64:1 \
  --out build/oa_writer_geometry/formal_simulation
python3 test/oa_writer_geometry/run_four_state.py \
  --out build/oa_writer_geometry/four_state
python3 test/oa_writer_geometry/run_equivalence.py \
  --out build/oa_writer_geometry/numeric
python3 scripts/fpga/open_fpga_synth.py \
  --case-config test/oa_writer_geometry/synthesis_cases.json --cases oa_writer \
  --out build/oa_writer_geometry/synthesis
```

测试入口自动解析模块依赖，并记录源码、共享辅助模块和日志的 SHA-256。Icarus 使用等价的正整数参数声明以兼容其解析器。完整参数、通过数量及映射指标见 [validation.json](validation.json)。
