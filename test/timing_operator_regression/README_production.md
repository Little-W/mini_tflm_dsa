# 当前 SoC 配置的 62 项算子回归

`run_production.py` 使用固定的 36 项共同算子和 26 项补充数值算子，检查实际输出、每项完成周期以及 19 项 DMA 与事件统计。两次运行使用同一组输入文件、AXI 存储模型和生产参数，分别编译指定提交的 RTL。

## 硬件参数

`production_parameters.json` 保存 `soc_d8699b87` 综合配置对应的 NPU 参数、来源摘要和派生参数。测试台显式绑定全部 37 项 `npu_top` 参数，并在每个算子开始前检查参数传递和派生值。

| 项目 | 当前配置 |
| --- | --- |
| NPU 地址宽度、控制寄存器宽度 | 32、32 |
| 矩阵维度计数宽度 | 29 |
| 阵列、操作数宽度 | 16 × 16；16 位 |
| AXI 数据宽度 | 64 位 |
| 矩阵输出量化并行度 | 2 |
| 向量模块的独立深度卷积量化并行度 | 1 |
| 向量 PE、窗口通道 | 8、8 |
| 共享存储 | 7 个存储体，每个 8192 字节 |
| 部分和物理存储池 | 49152 字节，固定 32 位表示 |
| 部分和帧数、`PS_STORAGE_ROWS` 参数 | 16、799 |
| im2col 缓存 | 4096 字节；128 字节缓存行；16 组、2 路 |
| IA 最大复用数、量化最大 IA 复用数 | 16、16 |
| 输出银行数：8 位、16 位 | 32、4 |
| IS 偏置行地址宽度、有效行计数宽度 | 8、9 |
| IS 模式能力、逐通道量化能力 | 开启、开启 |
| IA 紧凑存储 | 关闭 |
| AXI 读、写在途请求上限 | 4、4 |
| 最大 DMA 请求 | 2048 字节 |

结果中的 `matrix_requant_compute_lanes` 对应 `npu_top.REQUANT_COMPUTE_LANES`，并逐层检查到 `u_matrix_engine.u_output_pipeline.u_vec_requant.p_compute_lanes`。`vector_quantization_lanes` 对应 `g_vector_engine.u_engine.QUANT_LANES`。执行器保留的 `quantization_lanes` 字段也表示向量模块的独立量化并行度。

仿真启用 `SYNTHESIS`、`XILINX_FPGA`、`GEMPACT_PS_COMPRESS` 和 `GEMMORA_PS_FORCE_RAW`。部分和池宏为 49152 字节。模拟器在测试台中读取实际层次参数；任何参数不一致都会终止对应测试。

## 周期测量范围

测试直接驱动 `npu_top` 的任务配置接口，计时从接受任务开始，结束条件包括 NPU 完成和 AXI 响应全部接收。外部存储使用固定测试模型：首次读取响应为 8 个周期，连续读取每周期 1 拍，读地址接受间隔至少 1 个周期。

这些周期描述固定外部存储条件下的 NPU 算子执行。CPU 指令执行、AXI-Lite 配置事务和 SoC 外层互连由整机测试分别验证。

## 运行方法

准备独立参考工作目录：

```sh
git worktree add --detach ../rtl_reference 2247144937c2fd04039b9b005151f371d6b51f8f
git -C ../rtl_reference submodule update --init --recursive
```

固定输入可由现有生成器重建：

```sh
python test/timing_operator_regression/run.py \
  --repo ../rtl_reference \
  --out ../measurements/input_build \
  --prepare-only
```

运行参考版本：

```sh
python test/timing_operator_regression/run_production.py \
  --repo ../rtl_reference \
  --out ../measurements/production_reference \
  --inputs-from ../measurements/input_build/inputs \
  --jobs 1
```

为候选提交建立固定工作目录后，使用相同执行入口和输入比较：

```sh
python test/timing_operator_regression/run_production.py \
  --repo ../rtl_candidate \
  --out ../measurements/production_candidate \
  --inputs-from ../measurements/input_build/inputs \
  --compare-with ../measurements/production_reference/all_cases.json \
  --jobs 1
```

两次运行分别使用同一执行入口目录中的测试程序。`--verilator` 可指定完整路径。`--prepare-only` 检查输入摘要并记录请求配置；`--collect-only` 根据完整结果目录重新汇总。编译前后检查 RTL 和验证源码摘要，两个算子集合复用同一个模拟器。

参考工作目录需要保留 `drivers/dsa_accel.c` 和同目录头文件，供生产调度器生成任务配置。稀疏工作目录可以排除 `drivers/tflm`，同时保留这些驱动文件。

## 比较内容

每项算子检查输出张量的 SHA-256，并在模拟器内比较完成后的全部外部存储内容。比较文件记录每项周期差，同时要求以下 19 个字段逐项相等：

`first_ar`、`first_r`、`last_r`、`first_aw`、`first_w`、`last_w`、`last_b`、`done`、`first_read_latency`、`read_latency_min`、`read_latency_max`、`read_commands`、`write_commands`、`read_beats`、`write_beats`、`read_outstanding_max`、`write_outstanding_max`、`read_burst_bytes_max`、`write_burst_bytes_max`。

`comparison.json` 的 `passed` 要求两版本均完成全部 62 项，输入摘要和硬件参数相同，全部输出相同，每项周期相同，且全部 DMA 与事件字段相同。字段缺失或缺少实际层次参数记录会直接返回失败。

## 结果与文件保存

- `invocation.json`：命令、源提交、输入摘要和生产参数文件摘要。
- `sim/build.json`：实际编译命令、每个编译输入的 SHA-256、模拟器 SHA-256。
- `collections/common36`、`collections/numeric26`：两组数值测试结果和实际配置。
- `all_cases.json`：62 项输出摘要、周期、19 项统计及每项实际层次参数。
- `comparison.json`：逐项比较及差异字段。
- `sim/object_archive.json`：对象清理与生成源码压缩记录，包括压缩前 SHA-256。

完成后保留模拟器、测试台、RTL 来源摘要和运行日志；生成的 C++ 源码使用 gzip 保存，可重建的编译对象自动删除。需要保留编译对象时使用 `--keep-objects`。

执行比较程序自身的检查：

```sh
python test/timing_operator_regression/test_production_runner.py
```

检查覆盖相同结果、19 个事件字段的逐个差异、缺失字段和实际参数日志。

## 参考版本结果

提交 `2247144937c2fd04039b9b005151f371d6b51f8f` 在上述生产参数下完成全部数值和外部存储检查。每项测试的层次参数断言通过，19 项 DMA 与事件字段均已记录。

| 集合 | 算子数量 | 周期之和 |
| --- | ---: | ---: |
| 共同算子 | 36 | 391103 |
| 补充数值算子 | 26 | 190286 |
| 合计 | 62 | 581389 |

逐项结果保存在 `reference_production_22471449.json`，配置、编译输入一致性和测试程序检查汇总保存在 `validation_production.json`。参考模拟器 SHA-256 为 `2c07d2b714b2e1f8161cfd72e7dc8c29323a48f39d381af71f66f7c6c846b496`。
