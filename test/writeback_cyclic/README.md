# 输出 FIFO 循环分组存储

`vec_s8_to_fifo` 和 `vec_s8_to_fifo_full` 提供 `p_cyclic_storage` 参数，默认值为 `0`。参数为 `1` 且 `VLEN=16`、`BUS_WIDTH=32/64` 时启用循环分组。`npu_top` 的 S8 输出实例启用此选项。

## 存储结构和周期

令 `B=BUS_WIDTH/8`。逻辑字节 `(tile,row,column)` 存放在物理分组 `(row+column)%B`，地址为 `tile*VLEN+row`，字节位置为 `column/B`。每个分组保存 `VLEN/B` 个字节，所有分组在同一时钟边沿写入一整行。

普通输出在所有分组中读取相同行号，再按行号旋转字节顺序。转置输出的第 `b` 个分组读取 `beat*B+((b-column)%B)` 行，选择 `column/B` 字节，再恢复输出次序。读使能、输出有效、反压、掩码、行结束标记和两项输出暂存的周期均保持。普通输出的首拍等待期间重新采样方向时，循环存储在同一边沿重新读取对应内容。

存储实例通过 `vec_s8_fifo_row_ram` 使用 `regfile`。同步同地址读写返回写入前的内容，未使能读取时保留输出。源代码不指定 RAM 类型。生产参数 `VLEN16/BUS64/BANKS32` 包含八个 `512×16` 存储器，总容量为 **65,536 bit**。综合工具自动选择八个 RAMB18E1，写端和读端均配置为 `READ_FIRST`，额外 BRAM 输出寄存器关闭。

## 转置配置保持条件

循环分组要求合并输出从开始至完成期间保持 `transpose_mode`。默认参数仍支持通用模块的实时配置输入。NPU 的实际控制满足以下条件：

- `run_is_mode` 仅在 `cfg_stage2_fire` 更新，该事件要求任务控制器和帧调度器同时空闲。
- 正常任务控制器在输出完成后返回空闲。`oa_writer` 的完成事件来源于最后一次 DMA 完成；AXI 写响应在对应数据传输完成后返回。
- 帧式执行关闭行合并，普通输出使用已保存的方向。最终帧等待输出完成，帧调度器在完成握手前保持忙状态。
- 错误恢复通过 `core_rst_n` 同时清空 FIFO 控制状态和运行方向。配置接受时，旧存储内容的有效标记已经清空。

`run_control_formal.py` 自动提取实际配置寄存和控制器表达式，并实例化实际 `oa_writer`，使用时序归纳验证上述模式更新及完成事件的局部控制条件。`npu_top_observer` 在实际 NPU 输入上并联默认布局，逐周期比较全部输出值，并检查配置接受、合并读取、帧式读取及输出完成时的控制状态。该观察器不增加输入假设。

观察器在仿真结束时输出 `NPU_FIFO_COMPARE_PASS`，包括 `cycles`、`coalesce_cycles`、`frame_cycles`、`ws_coalesce_cycles`、`is_coalesce_cycles`、`ws_to_is`、`is_to_ws`、`configurations` 和 `recovery_resets`。完整生产回归应同时检查合并输出、帧式输出、两种方向切换和恢复路径的实际计数。

## 验证结果

| 检查 | BUS32 | BUS64 |
|---|---:|---:|
| 默认布局与 `b8b34d5` 接口逐周期比较 | 81 项、12,392 字节 | 81 项、12,392 字节 |
| 循环布局与 `b8b34d5` 接口逐周期比较 | 81 项、12,392 字节 | 81 项、12,392 字节 |
| 全部存储位置与读写次序 | 32,800 周期、129,152 字节 | 26,656 周期、209,152 字节 |
| 同地址读写 | 4,130 次 | 2,120 次 |
| 读使能暂停 | 2,528 次 | 2,529 次 |
| 实时方向变化测试 | 200,000 周期、99,345 次变化 | 200,000 周期、99,345 次变化 |
| 普通首拍等待期间改变方向 | 2,160 次 | 2,671 次 |

两种总线的地址、写入字节和读出选择全输入 SAT 均通过。配置与控制器的两组时序归纳、实际输出写入器的一组时序归纳均通过。生产配置的完整容量展开通过，S8 输出存储为 65,536 bit，包含 60 个 `regfile` 实例，总声明状态为 797,559 bit。

```sh
python test/writeback_cyclic/run.py --out build/fifo_bus32 --bus-width 32 --cyclic 1
python test/writeback_cyclic/run.py --out build/fifo_bus64 --bus-width 64 --cyclic 1
python test/writeback_cyclic/run.py --out build/fifo_default32 --bus-width 32 --cyclic 0
python test/writeback_cyclic/run.py --out build/fifo_default64 --bus-width 64 --cyclic 0
python test/writeback_cyclic/run_storage.py --out build/fifo_storage
python test/writeback_cyclic/run_modes.py --out build/fifo_modes
python test/writeback_cyclic/run_control_formal.py --out build/fifo_control
python test/capacity/check_elaboration.py --config config/npu_fpga.mk --verilator verilator-modern --output-root build/fifo_capacity
```

## 生产 NPU 附加任务

`run_npu.py` 复用已有生产仿真程序，执行 15 个连续任务。任务包含 WS/IS 两种合并输出、组尾、WS/IS 帧式输出、INT16 输出、写响应错误、读响应错误、无效复用配置和各自恢复任务。所有非帧式任务明确检查 `frame_commands=0`，两项帧式任务检查帧命令实际执行。

任务根据仿真程序 `build.json` 中的 `IA_COMPACT_ENABLE` 选择输入存储块数量。WS 使用左操作数格式，IS 使用 INT8 权重格式；紧凑格式需要至少一个输入存储块，非紧凑格式需要至少两个。案例明确要求的存储块数量继续保留。当前生产配置包含七个 8,192 字节共享存储块，关闭紧凑格式，因此各任务分配两个输入存储块和五个部分和存储块。

`1d2f7f6a` RTL 的 FPGA 与 ASIC 仿真程序均通过 15 项任务，各检查 11,392 个 INT32 累加值，任务周期合计为 51,371。观察器记录 9,181 个合并输出周期、1,804 个帧式输出周期、六次 WS 转 IS、四次 IS 转 WS 和三次错误恢复。全部任务的数值比较、命令模式和观察器计数检查均通过。结果和源文件校验值保存在 `test/ps_compression/input_configuration_validation.json`。

```sh
python test/writeback_cyclic/run_npu.py --out build/fifo_npu_modes --sim build/fpga_integration/npu/s16
```

## 独立综合和实际布局

同一正式 RTL、相同参数和相同封装引脚下，仅改变 `p_cyclic_storage`：

| 资源 | 默认布局 | 循环分组 |
|---|---:|---:|
| 逻辑 LUT | 2,167 | 1,615 |
| 分布式存储的标称 LUT 位置 | 1,376 | 0 |
| 普通寄存器 | 1,304 | 280 |
| RAMB18E1 | 0 | 8 |
| 实际物理 LUT 位置 | 3,732 | 1,723 |
| 其中用于逻辑 | 2,356 | 1,723 |
| 其中用于分布式存储 | 1,376 | 0 |
| 最长寄存器间组合路径单元数 | 12 | 12 |

实际布局减少 **2,009 个物理 LUT 位置**。本次独立测量完成打包和合法布局；150 MHz 时序由完整器件时序分析确认。详细源文件校验值、工具校验值和结果保存在 `measurement.json`。

`cases.json` 可直接传给 `scripts/fpga/open_fpga_synth.py`。`prepare_placement.py` 从映射网表确认 `coalesce_rows/cols` 高 27 位没有逻辑使用者后，在独立布局副本中移除这些无用封装端口，并为两种配置生成相同约束；原映射网表保持完整。随后使用 `open_fpga_implementation.py --through place` 执行实际布局，设置 `XC7_FRACTURE_LUTS=1`、`XC7_CARRY_DIRECT_DI=1`，目标器件为 `xc7a200tfbg484-3`。
