# 窗口描述符输入路径

窗口队列在更新 `count` 的同一边沿保存 `busy`，取值为已截断的 `next_count != 0`。复位和配置清除同时将两者置零。描述符选择直接读取占用寄存器，队列容量、请求接受、响应退休和所有字段的输出周期保持一致。

前端对行范围的高位部分采用三位分组比较，再按高位优先合并。生产配置的高位部分为 27 位，大小比较经过三级 LUT。与末项的相等比较使用同样的三位分组，末端合并低位求和、进位和边界条件。

快速接收条件分别比较位置、当前归约坐标和下一归约坐标。三个相等比较使用 33 位输入；位置与当前坐标的最高位补零，下一坐标保留完整进位位。每三个输入位形成一项相等结果，再合并为两个分组。最终接收条件由一个 LUT 合并，位置比较的两个分组直接进入该 LUT。

## 固定源码与验证

参考提交为 `b20921b3b1fc3351b1f6447dd688af12ac60ef19`。正式结果及源码 SHA-256 见 `measurement.json`。

- 前端组合证明直接提取两份实际源码，确认其余源码逐字相同。26 组无约束检查覆盖 `RW=1/4/5/6/16/31/32`、四种缓存策略、计数字段不同位宽，以及通用逻辑和官方 `LUT6` 功能模型。
- 队列证明使用实际参考与当前源码，在深度 2、3、4、7、8 下完成 20 项证明和 30 项条件检查。比较全部 179 位公开字段，包括无效周期字段，并检查完整原有状态和独立的 `busy` 不变量。公开输入保持任意，覆盖非空配置清除、暂停、错误状态、同周期入队与出队及启动与退休。复位时两份未复位描述符存储采用相同的任意二值内容。
- 实际 FPGA 窗口模型采用 `BUS_WIDTH=32`、`LANES=4` 和四项窗口队列，完成 422 个接收请求、418 个完成请求、4 个复位取消请求、4,457 个数值检查和 19 个错误场景。驻留数据的 1,545 行周期记录与参考逐字相同；连续 512 次响应用时 1,534 周期，最大响应间隔为 3 个周期。

## 映射结果

局部测量保留 DMA 的实际 `p0`、`q0`、行数字段选择和前端的实际范围、快速接收表达式。输入与结果各有寄存边界，`RW=5`、`CACHE_POLICY=3`，使用 Xilinx 7 系列映射。

| 局部指标 | 参考 | 当前 |
|---|---:|---:|
| 逻辑 LUT | 191 | 154 |
| 触发器 | 304 | 305 |
| CARRY4 | 5 | 2 |
| 任意输入到结果的最长组合路径 | 7 | 5 |
| 占用状态到 `tile_rows_in_range` | 7 | 5 |
| 占用状态到 `incoming_fast` | 7 | 5 |
| 占用状态到 `incoming_q_fast` | 6 | 4 |

实际四项窗口队列独立映射结果如下。两种测量各自具有明确边界，资源数分别记录。

| 队列指标 | 参考 | 当前 |
|---|---:|---:|
| 逻辑 LUT | 127 | 124 |
| 触发器 | 111 | 112 |
| 分布式存储 LUT | 76 | 76 |
| 最长寄存器间组合路径 | 5 | 6 |

这里的路径级数包含实际相连的 LUT、进位单元及其他组合单元。完整 SoC 的面积、跨模块路径和布局结果由固定整机测量报告记录。

## 运行方法

在配置好 Yosys Python 运行环境与 `verilator-modern` 后执行：

```bash
python3 test/frontend_tile_input_depth/formal.py \
  --reference b20921b3 --out build/frontend_tile_input_depth/formal
python3 test/frontend_tile_input_depth/queue_formal.py \
  --candidate rtl/npu/dma/conv_window_queue.sv \
  --reference b20921b3 --out build/frontend_tile_input_depth/queue_formal
python3 test/frontend_tile_input_depth/synthesis.py \
  --proof build/frontend_tile_input_depth/formal \
  --out build/frontend_tile_input_depth/local \
  --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock
python3 test/frontend_tile_input_depth/queue_synthesis.py \
  --reference b20921b3 --out build/frontend_tile_input_depth/queue_native \
  --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock
python3 test/window_dma/run.py --fpga --reference-ref b20921b3 \
  --verilator verilator-modern --jobs 1 \
  --out build/frontend_tile_input_depth/window
```

已有同源参考模型时，`window.py` 校验参考源码 SHA-256 后复用该模型；当前模型仍由实际 RTL 重新构建和执行。
