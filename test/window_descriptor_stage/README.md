# 窗口描述符准备与前端组合路径

## 数据流

`conv_window_queue` 在当前窗口执行期间，提前读取下一项的 `p0`、`q0`、`cols` 并保存到描述符寄存器。只有准备完成的描述符才向前端提供有效请求。列数是否处于 `1` 至 `p_max_cols` 范围，在请求接收时计算并与原队列位置一同保存；该结果随描述符交给 DMA。

四项请求容量、标签、请求顺序以及最后一次响应触发的队列更新规则保持一致。准备寄存器保存的描述符仍占用原队列位置。复位和重新配置会清除准备标志，错误响应继续按已接受的标签顺序完成。

前端配置地址检查并行计算四个字节的进位关系，随后合并最高位溢出结果。`LANES=3/4` 的组末判断分别比较剩余零、一、二、三个通道；组末减一、减二和减三值与配置一同保存。前端自身的公开周期保持一致。

## 延迟与吞吐

新进入空队列的描述符先完成一个准备周期，再由前端接收。队列已有后续请求时，这个准备周期与当前窗口执行重叠。

实际 FPGA 模型的常驻窗口测试中，首次请求接收到首次响应的间隔由 4 周期变为 5 周期。128 个连续 16 列请求仍产生 512 次响应，响应区间为 1534 周期，最大相邻响应间隔为 3 周期。

连续短窗口测试先在背压状态下填满四项队列，再开放响应。每种列数检查 64 个请求：

| 列数 | 响应次数 | 数据元素数 | 最大响应间隔 | 首次至末次响应周期数 |
|---:|---:|---:|---:|---:|
| 1 | 64 | 64 | 2 | 126 |
| 2 | 64 | 128 | 2 | 126 |
| 3 | 64 | 192 | 2 | 126 |
| 4 | 64 | 256 | 2 | 126 |
| 5 | 128 | 320 | 3 | 382 |
| 7 | 128 | 448 | 3 | 382 |
| 8 | 128 | 512 | 3 | 382 |
| 12 | 192 | 768 | 3 | 574 |
| 15 | 256 | 960 | 3 | 766 |
| 16 | 256 | 1024 | 3 | 766 |

该测试连同缓存预热共接受并完成 641 个请求，检查 4688 个数据元素，总计 4149 周期。

## 联合综合

固定参考提交为 `16913ce0`。联合综合包含实际窗口队列、DMA 描述符选择和完整前端。线性 DMA、缓存、预测器、读写地址保护及读通道选择六个外围模块作为接口边界。参数为 `SIZE=64`、`IM2COL_SIZE=16`、`BUS_WIDTH=64`、`CACHE_BLOCKS=64`、`CONV_CACHE_SETS=128`，前端为 `LANES=4`。

| 项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 7624 | 7653 |
| 分布式 RAM LUT | 76 | 56 |
| 两项 LUT 合计 | 7700 | 7709 |
| 触发器 | 3377 | 3485 |
| DSP48E1 | 33 | 33 |
| CARRY4 | 851 | 855 |
| 寄存器间最长组合单元数 | 16 | 15 |

逐位连接图完整，DSP 内部寄存边界及组合运算均计入路径。前端独立综合结果为 7299 个逻辑 LUT、3273 个触发器、30 个 DSP，最长组合路径同样为 15 级。完整 SoC 的物理 LUT 数量及 150 MHz 时序由整机实现报告统计。

## 功能验证

队列使用时序归纳证明。参考队列按照准备完成信号接收同一组前端启动事件，所有已写槽位、队列指针、占用计数、有效描述符和有效响应逐项相同。初始复位之后，所有外部输入保持任意取值。检查包含深度 `2/3/4/7/8`、最大列数 `16`，以及深度 `3` 配合最大列数 `1/4/31`，八组均在一步归纳中通过。

前端完整状态比较覆盖生产配置 `SIZE=16/LANES=4/CACHE_SETS=128/CACHE_WAYS=2/LINE_BYTES=16/BUS_WIDTH=64`。其中 88443 个观察位由直接 SAT 比较证明，三个组末通道判断结合实际源码的组合证明与 62 位派生状态的时序归纳证明。该组合验证覆盖 88446 个状态及输出观察位。`SIZE=4/LANES=3` 的小配置另检查 17910 个观察位，两种配置共计 106356 个观察位。配置地址溢出检查另对全部 64 个输入位证明相同结果；组末比较分别检查 `LANES=3/4` 下全部 32 个通道输入位。

实际 FPGA 窗口数值测试完成 422 个请求，其中 418 个完成，4 个由复位取消；检查 4457 个数据元素和 19 次预期错误响应。测试包括请求撤销、中止、配置取消、窗口授权后到达的普通请求、随机坐标与背压、错误排空、非法列数、配置等待以及四项在途请求复位。C++ 编译单元均启用未定义行为检查。

所有修改源码的 SHA-256、形式验证结果、数值日志、响应周期记录及综合资源保存在 `docs/data/window_descriptor_stage_validation.json`。

## 复现

```bash
python3 test/window_descriptor_stage/formal.py \
  --reference 16913ce0 --out build/window_descriptor/formal
python3 test/window_descriptor_stage/formal.py \
  --reference 16913ce0 --depths 3 --max-cols 1 --out build/window_descriptor/formal_cols1
python3 test/window_descriptor_stage/formal.py \
  --reference 16913ce0 --depths 3 --max-cols 4 --out build/window_descriptor/formal_cols4
python3 test/window_descriptor_stage/formal.py \
  --reference 16913ce0 --depths 3 --max-cols 31 --out build/window_descriptor/formal_cols31
python3 test/window_descriptor_stage/frontend_arithmetic.py \
  --reference 16913ce0 --out build/window_descriptor/arithmetic
python3 test/conv_frontend/tools/run_state_equivalence.py \
  --reference-ref 16913ce0 --cases size16_lanes4_policy3 size4_lanes3 \
  --group-proof build/window_descriptor/arithmetic/summary.json \
  --out build/window_descriptor/frontend_state
python3 test/window_dma/run.py --fpga --verilator verilator-modern \
  --jobs 1 --out build/window_descriptor/fpga
python3 test/window_descriptor_stage/short_windows.py \
  --model-dir build/window_descriptor/fpga --out build/window_descriptor/short \
  --verilator-include /path/to/verilator/include
python3 test/window_descriptor_stage/synthesis.py \
  --reference 16913ce0 --out build/window_descriptor/synthesis
python3 test/conv_frontend/tools/synthesis.py \
  --lanes 4 --out build/window_descriptor/frontend_native
```
