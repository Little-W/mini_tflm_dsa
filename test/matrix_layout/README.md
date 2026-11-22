# 分块矩阵布局与容量回归

本测试实例化完整的 `npu_axil_top`，通过 AXI-Lite 配置矩阵装载器、脉动阵列、
部分和存储、量化过程和输出 DMA。AXI 存储模型使用
`test/conv_npu/axi_memory.sv`，覆盖固定等待和随机等待。

```sh
python3 test/matrix_layout/run.py --profiles 8 4 16 --jobs 2
```

完整数值测试需要支持 SystemVerilog 时序的 Verilator 和 C++20 编译器。
`--verilator` 指定工具，`--out` 指定结果目录，默认目录为 `build/matrix_layout`。
`--skip-build` 在 RTL 和测试源码摘要均相同时复用已有程序；
`--case REGEX` 按名称选择任务。

`--lint-only` 检查实际硬件参数、模块依赖和层次引用，不生成 C++ 程序。
源文件列表使用工程的 `with_dependencies` 补齐公共模块，并按 package 引用关系排序。

```sh
python3 test/matrix_layout/run.py --lint-only --profiles 8 4 16 \
  --out build/matrix_layout_lint
python3 test/matrix_layout/run.py --lint-only --profiles 8 --ws-only \
  --out build/matrix_layout_ws_lint
```

`--ws-only` 设置 `ENABLE_IS_MODE=0`，并选择实际使用 WS 的任务。寄存器检查同时
确认 `MATRIX_CAPS` 的 IS 支持位与实例参数一致。

## 硬件参数

各配置使用 16×16 阵列、16 个部分和帧、799 行部分和容量、32 个 INT8 输出存储块、
4 个 INT16 输出存储块，以及最多 4 个未完成 AXI 读请求和 4 个未完成写请求。
`--profiles` 将 IA 缓存设置为 8、4 或 16 个分块。上述容量均显式传递给生产顶层。

AXI-Lite 检查读取 `0xe4` 的 `MATRIX_CAPS`、`0xe8` 的 `MATRIX_PS_ROWS` 和
`0xec` 的 `MATRIX_OUTPUT_BANKS`，并将返回值与实例参数比较。测试覆盖只读寄存器写入、
AW/W 分别到达、响应等待、布局标志的字节写使能、START 位写屏蔽，以及忙期间拒绝配置写入。

## 任务与检查

- WS 和 IS 的行优先、分块布局 LHS/RHS 组合。
- 完整分块、归约尾部、输出行列尾部、多个复用组、INT8/INT16 输入、非零输入修正、
  整张量及逐通道量化、激活范围和舍入到最近偶数的中点值。
- INT16×INT8 计算与 INT16 输出。通过延迟写入填满 4 个 INT16 FIFO 存储块，检查容量、
  未读数据保护、反压和最终输出。即使配置的 IS 选择位为 1，INT16 输出任务仍使用 WS；
  专门任务覆盖该选择与尾部分块、部分和容量限制的组合。
- 两种数据流的原生卷积与分块 RHS 权重。LHS 使用分块卷积布局的无效配置应在任何
  AXI 访问之前报告配置错误。
- IS 逐通道组的 `R=4,W=1`、`R=4,W=2` 和 63 个输出通道。IA16 还覆盖
  `R=8,W=4` 与 127 个通道的尾组。
- 恰好需要 799 行部分和、超出容量和无需中间部分和的单个归约分块。
  IA16 下申请 8 个 INT16 输出存储块的任务应在存储访问前被拒绝。
- 在 4 KiB 边界结束的读写、独立 AXI 通道等待、连续任务、读写响应错误注入、
  最后一个偏置局部请求上的错误，以及错误后的成功任务。

INT16 FIFO 的容量和写入检查访问
`u_dut.u_npu_top.u_matrix_engine.u_output_pipeline.u_vec_s16_to_fifo`。
占用量为 `ready_bank_count_q` 加上 `write_ptr` 非零时的一个写入中存储块。
分块数量使用该 FIFO 的 `in_valid` 和 `in_tile_done` 统计，输入已包含生产输出模式选择。
任务超时信息读取 `u_matrix_engine.u_npu_controller.current_state`。

分块操作数的物理形状为 `[ceil(rows/16), ceil(K/16), 16, 16]`，每个分块内部按行存放。
LHS 行对应输出矩阵行，RHS 行对应输出矩阵列。测试在归约填充区写入非零值，
确认装载器清除逻辑 `K` 之外的元素；末尾分块的无效行不属于允许读取的区域。

参考计算使用 Python 任意精度整数点积，以及舍入到最近偶数的整数除法。
INT16 输出使用缩减后的 Q31 乘数和有符号乘积。有效累加结果均位于有符号三十二位范围。
卷积参考独立生成 NHWC 窗口，包含输入修正后的零填充。

每个 AXI 读请求按输入、权重、偏置和量化参数的逐字节分配表检查。每个有效写使能
必须对应输出字节。成功任务比较完整的 512 KiB 存储映像，包括输出步长填充和非输出数据。
配置错误应保持存储内容不变。写响应错误注入时，每个输出字节可以保持原值或具有正确计算值，
非输出字节仍要求完全一致。任务完成时应已接收所有存储响应。

## 结果文件

当前入口验证见 `entry_validation.json`。IA 缓存为 4、8、16 个分块的配置，以及
IA 为 8 个分块且仅启用 WS 的配置，均通过当前源码的 lint。

`summary.json` 保存任务结果与统计数据。各配置的 `build.json` 保存编译源码摘要、命令
和程序摘要；仅执行 lint 时保存 `lint.json`。每个任务生成 `case.json`、`config.mem`、
`init.mem`、`golden.mem` 和 `access.mem`，记录矩阵形状、布局标志、量化模式、复用数、
容量需求及预期输出 SHA256。

周期统计包含 AXI-Lite 启动和状态轮询。加速器性能比较使用工程中的专用性能测试。

偏置存储的定向回归覆盖 1、2、4 和 8 个分块容量下的驻留组复用和局部组边界：

```sh
make -C test/bias_loader_reuse run JOBS=2
```
