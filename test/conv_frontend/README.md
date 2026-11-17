# 硬件 im2col 前端独立验证

本目录使用直接数学公式生成期望值，并编译仓库 `rtl/npu/conv/` 中的生产模块进行 RTL 验证。

```bash
# 实际 RTL：8 组配置，以及 AXI span 和控制错误回归
python test/conv_frontend/tools/run_rtl_suite.py

# Native geometry：policy 1/2 的调度信息、预测器启动和 IA 写入
python test/conv_frontend/tools/run_native_geometry.py

# 独立的模型 / GCC C 直接卷积参考对照
python test/conv_frontend/tests/run_model_tests.py
```

输入、tile 描述符和直接数学公式期望值均在运行时生成。所有日志、状态、向量和编译目录默认位于仓库根目录的 `build/conv_frontend/`，不读取归档结果。

## RTL 覆盖

每组前端配置运行 37 个任务，覆盖矩形核、stride/dilation、padding、归约尾部、非对齐 p0/q0、乱序 tile、S8/S16 数值极值、非零 input_offset、缓存旁路、同地址换内容失效、读错误和下一任务恢复，以及接近 4 GiB 的读裁剪。配置握手后将外部 cfg 清零，确认正在执行的配置已经锁存。总线 AR/R 和 tile 写端有随机停顿，并核对实际 AXI 读字节与硬件统计值一致。

| SIZE | sets | ways | line bytes | 入口 |
|---:|---:|---:|---:|---|
| 4 | 128 | 2 | 16 | 直接 descriptor |
| 8 | 128 | 2 | 16 | 直接 descriptor |
| 16 | 128 | 2 | 16 | 直接 descriptor |
| 4 | 128 | 2 | 16 | `conv_ia_tile_path` + 写口适配器 |
| 4 | 2 | 1 | 8 | 直接 descriptor |
| 8 | 2 | 2 | 32 | 直接 descriptor |
| 16 | 2 | 1 | 32 | `conv_ia_tile_path` + 写口适配器 |
| 16 | 2 | 2 | 256 | 直接 descriptor |

另外，AXI span testbench 检查 251 个请求，覆盖 65535 字节长度、首尾非对齐、4 KiB 分段、高地址、AR/R/响应端等待和 RRESP 传播；实际检查 913763 个读取字节、2043 个 burst。控制 testbench 检查 23 个配置/描述符与恢复事件，包括溢出、非法 offset、S16 对齐、运行中配置等待和失败后恢复。

## Native geometry 检查

`run_native_geometry.py` 默认分别编译和运行 policy 1、policy 2。输入为 NHWC 1×1×16，卷积核为 1×1，输入基址为 `0x1000`，启用 windowed 和 prefetch。原生调度参数 `cfg_sched_r=1`、`cfg_sched_groups=1`，tile 参数为 `p0=q0=0`、一行、16 列。

测试比较全部 16 个 IA 输出值，检查 geometry predictor 恰好启动一次，并检查任务完成时外部读事务已结束。总仿真周期限制为 2000。默认结果目录为 `build/conv_frontend/native_geometry/`，其中 `summary.json` 包含各策略的执行命令、状态文件、源文件与向量 SHA-256。

```bash
python test/conv_frontend/tools/run_native_geometry.py --policies 1 2
```

`--out` 可指定结果目录。现有 testbench 的 `NATIVE_SCHED_R`、`NATIVE_SCHED_GROUPS` 默认值均为 0，`EXPECT_GEOMETRY_PREDICTIONS` 默认为 −1，表示不要求特定预测次数。通用 `run_rtl.py` 提供对应的 `--native-sched-r`、`--native-sched-groups` 和 `--expect-geometry-predictions` 参数，并支持 `--vectors`、`--max-cycles` 和 `--out`。

## 事务与编译检查

读错误用例选择中心核 `q0 = group_c * (kernel_w + 1)`，使该任务产生外部读取。测试检查读错误传播、任务恢复，以及外部事务结束状态。

测试包含除法器与缓存状态断言，并审查所有 Verilator 诊断。宽度、符号、锁存器、多驱动、组合循环等诊断会使测试失败。允许的诊断包括结构中的未使用字段、测试记分板赋值风格、同步断言观察异步复位。完整诊断保留在日志中。

每次执行生成 `build/conv_frontend/frontend_rtl_suite_status.json`，包括实际工具版本、每个测试命令、所有诊断和本次 PASS/FAIL 统计。

## 范围说明

本目录覆盖前端、缓存、精确范围读取器及两个适配模块。完整 NPU 的 IA 调度、脉动阵列、bias、逐通道量化、写回，以及 CPU/NMSIS 分发，由对应的 NPU/SoC 测试验证。模型/C 数值参考、实际 RTL 仿真与 NMSIS 二进制测试分别记录结果。
