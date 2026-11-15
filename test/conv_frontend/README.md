# 硬件 im2col 前端独立验证

本目录沿用交接包的直接数学公式期望值生成器，扩展了实际 RTL 验证。所有仿真直接编译仓库 `rtl/npu/conv/` 中的生产模块，没有复制另一套 RTL。

```bash
# 实际 RTL：8 组配置，以及 AXI span 和控制错误回归
python test/conv_frontend/tools/run_rtl_suite.py

# 独立的模型 / GCC C 直接卷积参考对照
python test/conv_frontend/tests/run_model_tests.py
```

输入、tile 描述符和直接数学公式期望值均在运行时生成。所有日志、状态、向量和编译目录默认位于仓库根目录的 `build/conv_frontend/`，不读取归档结果。

## RTL 覆盖

每组前端配置运行 37 个任务：原交接形状、矩形核、stride/dilation、padding、归约尾部、非对齐 p0/q0、乱序 tile、S8/S16 数值极值、非零 input_offset、缓存旁路、同地址换内容失效、读错误和下一任务恢复，以及接近 4 GiB 的读裁剪。配置握手后将外部 cfg 清零，确认正在执行的配置已经锁存。总线 AR/R 和 tile 写端有随机停顿，并核对实际 AXI 读字节与硬件统计值一致。

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

## 真实失败与修正

原交接测试 SIZE=4 在最后的“读错误”任务失败：指定的 tile 全在 top padding 中，没有任何外部读，因而不能触发 RRESP 错误。源码版本不包含历史失败日志。修正后的测试选择中心核 `q0 = group_c * (kernel_w + 1)`，确保实际产生读取；测试还检查外部事务确实排空。

源码修正了显式位宽转换并补充除法器与缓存状态断言。测试审查所有 Verilator 诊断：宽度、符号、锁存器、多驱动、组合循环等未列入允许范围。仅允许已审查的结构未使用字段、测试记分板赋值风格和同步断言观察异步复位等诊断，以及为源码排序使用 `00_conv_im2col_pkg.sv` 这个具体文件名产生的诊断。完整诊断保留在日志中。

每次执行生成 `build/conv_frontend/frontend_rtl_suite_status.json`，包括实际工具版本、每个测试命令、所有诊断和本次 PASS/FAIL 统计。

## 范围说明

本目录的 RTL 结果只证明前端、缓存、精确范围读取器及两个适配模块的功能。原 NPU 的 IA 调度、脉动阵列、bias、逐通道量化、写回，以及 CPU/NMSIS 分发，需要对应的 NPU/SoC 测试。这里的模型/C 对照也不代替真实 RTL 或 NMSIS 二进制验证。
