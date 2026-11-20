# 权重加载器有界未完成计数

`kernel_loader_ctrl` 保留完整宽度的 `issued_count`，使用两个 2 位寄存器记录尚未完成加载和发送的块数。生产配置 `COUNT_WIDTH=29` 的累计计数仍按 87 位无符号运算处理，任务维度、缓存容量、接口和公开周期均保持。

## 计数与真实存储状态

设累计发出、加载完成和发送完成数量分别为 `I`、`L`、`S`，差值按累计计数的原始位宽计算。

- `pending_loads = I - L`，等于两个逻辑槽位中尚未收到加载完成的数量，范围为 0 至 2。
- `pending_sends = I - S`，等于逻辑槽位中的待发送块数，加上活动发送、发送预读和两级完成通知中的有效块数，范围为 0 至 3。
- 活动发送、发送预读和完成通知阶段互斥，单个块在这些阶段只占用一个位置。
- 缓存命中生成一个逻辑加载完成事件。推测预取占用的槽位在成为当前需求前不计入当前任务；丢弃预取不会减少当前任务的计数。

真实 `kernel_loader`、`kernel_loader_ctrl` 和 `kernel_loader_buffer` 的 48 项归属关系同时参与归纳，包含读写槽位次序、物理预取与逻辑需求的对应关系、DMA 返回、加载提交和发送完成阶段。由这些关系证明，在运行状态下：

1. 接受新逻辑请求时，`pending_loads < 2` 且 `pending_sends < 3`。
2. 加载完成时，`pending_loads > 0`。
3. 发送完成时，`pending_sends > pending_loads`。

控制器按同一边沿上的接受、加载完成和发送完成事件增加或减少差值。累计值之间的大小比较同时检查 `issued_count` 为 0、1 的情况，完整保留模计数回绕处的无符号比较结果。

## 验证组成

`run_formal.py` 从指定 Git 提交读取参考加载器，在当前源码上重建以下六项证明。默认参考提交为 `8d7dc595`。

| 检查 | 实际对象与结论 |
|---|---|
| `buffer` | 实例化真实缓存，证明加载差值最多为 2、发送差值最多为 3及物理占用关系 |
| `kernel` | 实例化真实加载器及参考控制器，证明 48 项归属关系、完整 87 位差值范围和全部接受/完成事件条件 |
| `control` | 比较参考控制器和当前控制器的 27 项状态、22 项公开输出，逐周期相同 |
| `comparisons` | 对任意 87 位累计发出数量证明最终加载与发送比较相同，覆盖回绕附近取值 |
| `linear` | 实例化真实线性 DMA，证明四项上下文队列的接收次序、槽位/标记存储、完成唯一性及返回归属 |
| `image` | 从实际 `axi_dual_block_dma` 提取完整图像任务接收及状态更新代码，证明图像任务只有一个完成通知，返回槽位和标记来自接受的描述符 |

加载器证明将描述符相等、遍历末端和累计大小比较的结果扩大为任意输入。因此证明不依赖缩小任务尺寸或限制累计次数。DMA 证明扩大行边界算术结果，保留真实上下文存储、接收和返回控制。脚本为新增信号统一分配编号，并检查每个内部信号只有一个驱动。

模型使用的外部条件是：DMA 完成对应已接受槽位；新加载命令开始时前一需求已发送完毕；命令模式在缓存清空前保持；生产配置清空发生在旧 DMA 结束之后。图像任务还要求活动图像处理期间没有线性完成事件。`test/monitors/kernel_loader_observer.sv` 将这些条件作为断言接到实际 NPU、真实仲裁器和 DMA 实例，同时用独立的 87 位累计参考计数检查每一个运行周期。测试不改变接口事件。

## 已完成结果

完整加载器包含已登记的描述符比较和双输出行组装。映射参数为 `SIZE=16`、`DATA_WIDTH=16`、`BUS_WIDTH=64`、`REG_WIDTH=32`、`COUNT_WIDTH=29`。

| 完整加载器 | 参考实现 | 有界未完成计数 |
|---|---:|---:|
| 逻辑 LUT | 4764 | 4662 |
| 分布式 RAM LUT | 384 | 384 |
| 触发器 | 2949 | 2779 |
| DSP | 6 | 0 |
| 寄存器之间最长组合级数 | 15 | 15 |
| 寄存器至 `prefetch_idle` | 8 | 8 |
| 寄存器至 `load_weight_req` | 5 | 5 |
| 寄存器至 `ext_dma_start` | 7 | 7 |

以上为 Xilinx 7 系列逻辑映射统计；物理 LUT 位置和 150 MHz 时序由完整 SoC 的布局布线结果确定。

六项形式证明全部通过。实际 FPGA 原语的 BUS32、BUS64 加载器测试各检查 285 块、72960 个数值，分别运行 45050、29443 周期；周期、DMA 请求/完成、预取、命中和丢弃统计均与参考实现相同。C++ 仿真各编译单元均启用 UBSan。

生产配置的完整 NPU 使用 7 个 8192 字节共享银行和原始部分和记录，完成以下测试：

| 完整 NPU 测试 | 任务数 | INT32 数值检查 |
|---|---:|---:|
| 常规卷积、Dense、不同精度与错误恢复 | 38 | 11118 |
| 生产容量、WS/IS 帧调度和非法配置状态 | 21 | 173642 |
| 受管卷积预取、图像描述符和错误后重新配置 | 6 | 8820 |

容量测试观察到 294 次受管初始化和 244 次预取命中；受管卷积测试观察到 114 次受管初始化、62 次预取命中，覆盖真实 `kernel_im2col_commands` 和 AXI 错误恢复。源码哈希、综合统计、形式日志哈希和运行结果保存在 `measurement.json`。

## 重复执行

形式验证要求 Python 环境提供仓库综合脚本使用的 `pyosys`：

```bash
python3 test/kernel_pending_counts/run_formal.py --out build/kernel_pending_counts/formal
python3 scripts/fpga/open_fpga_synth.py --out build/kernel_pending_counts/synthesis --case-config test/kernel_pending_counts/cases.json --cases kernel_pending_controller kernel_pending_loader
```

加载器原语和周期检查：

```bash
python3 test/kernel_prefetch/run.py --out build/kernel_pending_counts/bus32 --bus-width 32 --fpga --verilator verilator
python3 test/kernel_prefetch/run.py --out build/kernel_pending_counts/bus64 --bus-width 64 --fpga --verilator verilator
```

完整 NPU 仿真程序仅需编译一次，后两项检查验证该程序的参数和源码哈希后复用：

```bash
python3 test/conv_npu/run.py --sizes 16 --out build/kernel_pending_counts/npu --jobs 1 --ps-compress --pool-bytes 49152 --force-raw --bus-width 64 --shared-bank-bytes 8192 --shared-bank-count 7 --verilator verilator
python3 test/ps_capacity_limits/run_npu.py --out build/kernel_pending_counts/capacity --sim build/kernel_pending_counts/npu/s16 --bus-width 64 --verilator verilator
python3 test/kernel_pending_counts/run_npu.py --out build/kernel_pending_counts/managed_convolution --sim build/kernel_pending_counts/npu/s16
```
