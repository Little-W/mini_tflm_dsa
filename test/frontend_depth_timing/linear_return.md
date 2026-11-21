# 线性 DMA 返回列资格

`axi_linear_block_dma` 在 `rd_r_hs` 成立的原有时钟边沿保存 `rd_rsp_lane_in_data_r`。每个通道的资格由当前描述符的 `rd_head.valid_cols` 和当前返回拍的 `rd_rsp_col_base_comb` 计算，与返回数据、行列位置、元素格式、偏移和标签同时进入寄存器。没有增加流水级。

列资格计算保留原来的位宽、类型转换、截断、减法下溢以及列基址回绕。通用参数分支继续使用原有定宽表达式。`wr_valid` 仍由返回有效信号、元素格式和块内范围决定；块内超过有效列数的通道保持有效并写入零。复位清除资格寄存器，没有返回握手时保持原值。

## 完整状态与派生关系证明

`linear_return_check.py` 将两侧实际 `g_unpack_lane[lane].lane_in_data` 作为额外证明输出。参考侧使用已保存列信息的组合表达式，当前侧使用同拍保存的资格位。全部公开输出、共享时钟状态、展开后的描述符存储以及各通道资格一起参加归纳检查，不添加输入假设。

以下参数的全部组合共 32 项，均已通过。

| 参数 | 取值 |
|---|---|
| `SIZE` | 16、64 |
| `BUS_WIDTH` | 32、64 |
| `READ_OUTSTANDING` | 1、4 |
| `WRITE_OUTSTANDING` | 1、4 |
| `RD_CONTEXT_DEPTH` | 1、4 |

参考源码保存在 `linear_return_reference.sv`，SHA256 为 `7a22ff43b1d4f8f2c63cc01b1773533f1ea567530f05d7ba0e6ac5444ec088e2`。当前实现 SHA256 为 `aa5f400687a81064f97953216911684f4a57042e4f687528db8fe362d136aac0`。

```bash
python test/frontend_depth_timing/linear_return_check.py \
  --reference test/frontend_depth_timing/linear_return_reference.sv \
  --candidate rtl/npu/dma/axi_linear_block_dma.sv \
  --sizes 16 64 --out build/linear_return_mask/formal
```

## 真实 AXI 读取

32 位和 64 位总线分别执行固定响应与随机背压测试。每组均检查真实 AR/R 握手、4 KiB 分段、未对齐数据连接、8 位和 16 位元素、符号扩展、尾列补零、错误响应及描述符连续接收。四次执行合计通过 1324 条命令、16216 个物理突发、97228 个 AXI 返回拍和 449248 个输出元素。

| 总线宽度 | 背压模式 | 命令数 | 输出元素 | 周期数 |
|---:|---|---:|---:|---:|
| 32 | 固定 | 299 | 77824 | 24030 |
| 32 | 随机 | 299 | 77824 | 35171 |
| 64 | 固定 | 363 | 146800 | 35382 |
| 64 | 随机 | 363 | 146800 | 50251 |

```bash
python test/linear_dma_4k/run.py --bus-width 32 --outstanding 4 \
  --out build/linear_return_mask/read_b32
python test/linear_dma_4k/run.py --bus-width 64 --outstanding 4 \
  --out build/linear_return_mask/read_b64
```

`--source-root` 可以指定包含固定 RTL 的独立目录。摘要保存参与编译的全部源码 SHA256、可执行文件 SHA256 和每次执行的计数。

## 相同设置的综合与路径检查

两侧使用 `synth_xilinx -family xc7 -noiopad -noclkbuf -flatten`，参数为 `SIZE=64`、`BUS_WIDTH=64`、`CACHE_BLOCKS=64`、读写各四项在途事务和四项描述符。所有寄存器间路径均按映射后的实际连接计算。

| 项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 1896 | 1812 |
| 分布式 RAM 标称 LUT | 56 | 56 |
| 触发器 | 742 | 718 |
| CARRY4 | 193 | 193 |
| BRAM18 / DSP | 1 / 1 | 1 / 1 |
| 最长寄存器间组合路径 | 14 | 14 |
| 内部寄存器至 `wr_data` 的最大深度 | 8 | 6 |
| 返回列资格至 `wr_data` | 8 | 2 |

新资格寄存器的 D 输入最大深度为 9，CE 输入最大深度为 1。返回资格提前保存后，接收侧保持在 14 级要求以内。表中为独立线性 DMA 的结果，完整 SoC 的跨模块路径由整机综合检查。

```bash
python test/frontend_depth_timing/linear_return_measure.py \
  --reference test/frontend_depth_timing/linear_return_reference.sv \
  --candidate rtl/npu/dma/axi_linear_block_dma.sv \
  --out build/linear_return_mask/measurement \
  --lock-file /tmp/npu_synthesis_20261121.lock

python test/frontend_depth_timing/linear_return_collect.py \
  --formal build/linear_return_mask/formal \
  --measurement build/linear_return_mask/measurement \
  --read-tests build/linear_return_mask/read_b32 build/linear_return_mask/read_b64 \
  --out test/frontend_depth_timing/linear_return_measurement.json
```

汇总程序检查证明、实际读取和综合的源码及公共依赖一致，并保留逐配置结果、实际事务计数和路径统计。当前摘要见 [linear_return_measurement.json](linear_return_measurement.json)。
