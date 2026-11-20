# 前端字节偏移计算

有符号 8 位输入与 16 位 `input_offset` 相加时，各通道分别计算低 8 位和进位。
所有通道共用偏移高字节的原值、递增值和递减值，再根据输入符号与低字节进位选择高字节。
该结构保留完整 16 位模加结果，使晚到的字节选择经过较短的进位路径。
寄存器、握手、数据格式、缓存容量和接口周期保持一致。

参考提交为 `3c8cafeb2bb7029d903479ace4bd591e5109f03b`。
参考前端 SHA-256 为 `257f573697653f2ef5e87b06c39ef4a2c14cefb052b15eea687158bd072e802b`；
当前前端为 `09e839975af58a95997d9eefe7d7d1088c566c56e786e29a2a574b1a2b815a6e`。
完整报告保存于 `measurement.json`。

## 正式证明与数值检查

`formal.py` 直接读取当前和参考文件中的写入表达式，并确认其余前端源码逐字相同。
证明允许状态、地址、数据、通道掩码、尺寸和全部 65,536 个偏移位模式任意取值。
比较内容包括通道数、有效通道、字节选择、写掩码和各通道的完整 16 位数据。
`LANES=1、2、3、4、8` 五种配置均通过 SAT 等价证明。

数值测试使用实际 DMA、前端和缓存，以及官方 FPGA 原语功能模型。
窗口配置为 `BUS_WIDTH=32`、DMA 大小 64、前端大小 16、`LANES=4`、`CACHE_SETS=128`、`CACHE_BLOCKS=4`。

| 检查 | 结果 |
|---|---|
| 配置、背压、撤销、复位和错误恢复 | 422 个请求接收，418 个完成，4 个复位取消，4,457 个输出数值，19 个预期错误 |
| 连续驻留窗口 | 512 个响应，1,534 周期，最大响应间隔 3 周期 |
| 驻留窗口逐周期比较 | 1,545 行记录完全相同 |
| 每个合法偏移与全部字节值组合 | 偏移 −127 至 128、字节值 0 至 255，覆盖 65,536 个组合 |
| 连续及散布窗口数值 | 256 组配置序列，5,120 个完成请求，74,391 个输出数值 |
| 偏移窗口逐周期比较 | 318,777 行记录完全相同，共运行 318,782 周期 |

散布窗口同时覆盖三通道、3×3 卷积核、填充、非对齐地址和随机背压。
公开输出、请求顺序、队列状态及完成事件沿用窗口测试的逐周期记录。

## 映射结果

局部测量直接使用已证明的实际写入表达式，在输入和输出两侧添加测试寄存器，采用 `LANES=4`。
联合测量使用实际 `npu_top` 连接，保留 DMA、窗口队列、完整前端、缓存及 IA 控制和写入逻辑。
向量、计算阵列、共享存储、预测器和线性 AXI 传输单元保留接口边界，完整边界清单及每份源码 SHA-256 均记录在报告中。
联合参数为 `ADDR_WIDTH=32`、`BUS_WIDTH=64`、`SIZE=16`、`IA_SLOT_BLOCKS=32`。
两组测量均使用原生 Xilinx 映射；组合层数按真实逐位连接统计，并包含未寄存的 DSP 运算。

| 项目 | 参考版本 | 当前版本 |
|---|---:|---:|
| 局部逻辑 LUT | 213 | 217 |
| 局部触发器 | 270 | 270 |
| 局部状态到写入数据 | 9 级 | 8 级 |
| 联合逻辑 LUT | 22,806 | 22,916 |
| 联合触发器 | 12,234 | 12,234 |
| 联合 DSP48E1 | 72 | 72 |
| 联合 RAM LUT / RAMB18E1 | 660 / 20 | 660 / 20 |
| 前端寄存器到 IA 写入数据 | 16 级 | 15 级 |
| 前端寄存器到 IA 写入掩码 | 13 级 | 12 级 |
| 前端寄存器到 IA 写入使能 | 12 级 | 11 级 |

当前写入数据最长路径从前端 `state[4]` 到 IA 缓存 `ram_port_wr_data[217]`。
联合综合的最大驻留内存为 939,176 KiB，进程虚拟地址限制为 3 GiB。
表中 LUT 为该联合范围内布局前的逻辑原语数量。

## 运行

```bash
source /workspace/scratch/92f7be750f11/toolchain/env.sh
python3 test/frontend_s8_offset/formal.py --reference 3c8cafeb --out build/r21_s8_offset/formal
python3 test/frontend_s8_offset/synthesis.py --proof build/r21_s8_offset/formal --out build/r21_s8_offset/local
python3 test/window_dma/run.py --out build/r21_s8_offset/window --verilator verilator-modern --jobs 1 --fpga --reference-ref 3c8cafeb
python3 test/frontend_s8_offset/numeric.py --model build/r21_s8_offset/window --proof build/r21_s8_offset/formal/summary.json --verilator-include /workspace/scratch/92f7be750f11/toolchain/verilator/verilator/include --out build/r21_s8_offset/numeric
python3 test/frontend_s8_offset/joint.py --reference 3c8cafeb --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock --out build/r21_s8_offset/joint
python3 test/frontend_s8_offset/summarize.py --build build/r21_s8_offset --out test/frontend_s8_offset/measurement.json
```
