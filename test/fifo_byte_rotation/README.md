# INT8 FIFO 字节循环选择

## 实现

`vec_s8_to_fifo_full` 的循环存储布局使用分级字节旋转。写入时，每个总线宽度的数据组按行号循环移动；读出时，各存储体先选择相同的列组，再恢复输出字节顺序。FPGA 实现将每级相邻两个数据位的二选一运算放入同一个 `LUT6_2`。通用实现使用相同的循环移动表达式。

存储体数量、地址、写入掩码、读取使能和所有寄存状态保持原有行为。生产配置保存 32 个 16×16 INT8 数据块，共 65,536 位；接口的接收周期、输出周期和反压行为保持不变。

## 测量

测量配置为 `VLEN=16`、`BANKS=32`、`BUS_WIDTH=64`、`ENABLE_TRANSPOSE=1`、`p_cyclic_storage=1`。比较版本为 `3a773d18`，两个版本使用相同的 Yosys Xilinx 7 系列综合流程。

| 项目 | 比较版本 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT 原语 | 1,615 | 1,437 |
| 触发器 | 280 | 280 |
| RAMB18E1 | 8 | 8 |
| DSP48E1 | 0 | 0 |
| CARRY4 | 114 | 111 |
| 最长寄存器间组合路径 | 12 | 11 |

上述 LUT 数为单模块映射结果。完整 SoC 的物理 LUT 数由其独立的综合和布局报告提供。

## 验证

形式等价检查覆盖 7 组参数，包括 32 位与 64 位总线、3/16/32 个数据块、通用与 FPGA 实现，以及默认存储布局。检查使用实际模块的完整控制逻辑，比较全部公开输出、寄存状态和每个存储体的地址、使能、写数据。存储读数据作为任意输入参与比较，存储模块源码保持相同；复位、配置、数据、模式切换和反压输入均未增加取值限制。FPGA 分支使用 Yosys 提供的 `LUT6_2` 功能模型。

32 位与 64 位总线的 FPGA 存储测试共检查 338,304 个字节，覆盖 6,250 次同地址读写和 5,057 次读输出保持。完整 FIFO 事务比较共通过 162 个用例，检查 24,784 个字节并逐周期核对公开输出。模式切换测试执行 400,000 个周期，覆盖 198,690 次模式变化和 4,831 次首个输出周期等待期间的模式变化。

可重复执行的命令如下。运行环境需要 Pyosys 和 Verilator。

```sh
python3 test/fifo_byte_rotation/run_formal.py --out build/fifo_rotation/formal
python3 test/writeback_cyclic/run_storage.py --out build/fifo_rotation/storage_fpga --fpga
python3 test/writeback_cyclic/run.py --out build/fifo_rotation/bus32_fpga --bus-width 32 --reference-rev 3a773d18 --fpga
python3 test/writeback_cyclic/run.py --out build/fifo_rotation/bus64_fpga --bus-width 64 --reference-rev 3a773d18 --fpga
python3 test/writeback_cyclic/run_modes.py --out build/fifo_rotation/modes
```

源文件摘要、综合资源、路径检查及各项验证结果保存在 `measurement.json`。
