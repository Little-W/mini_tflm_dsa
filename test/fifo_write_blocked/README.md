# INT8 FIFO 写入阻塞状态

本文保存的资源与路径记录使用当次固定源码、RTL 算术属性选择和 740 个 DSP 的总预算，具体源码与配置见随文测量报告。文中的运行命令用于当前工作区，采用普通 RTL 自动映射并生成新的资源与路径报告。

`vec_s8_to_fifo_full` 在银行有效位和写入位置更新的同一边沿，保存当前写入银行及下一写入银行的阻塞状态。释放与写入同时发生时，银行有效位保持释放优先级。`fifo_full_flag` 直接使用保存的阻塞状态，读写接口及输出周期保持一致。

流式输出同时保存当前行位置加一的结果和转置行数。普通模式与转置模式分别比较行范围，随后使用普通 `case` 选择结束条件；未知模式使用完整行数表达式。所有配置使用同一份可综合控制逻辑。

## 检查方法

`run_formal.py` 比较完整控制、共同寄存状态、公开输出及数据存储的地址、使能和写数据。数据 RAM 返回值使用双方共有的任意输入。首次复位后不限制功能输入或后续复位。新增状态关系与独热写入位置关系作为输出共同证明。

`run_four_state.py` 保留实际控制和计数存储，逐周期比较 24 项共同状态、13 类输出及存储端口、4 项保存状态关系。参数覆盖 1 至 64 个银行、32 位和 64 位总线、8 至 32 路向量以及两种存储布局；刺激包含连续写入、等待、合并输出、运行中复位和 X/Z 控制。

数值测试复用 `fifo_read_qualification/run_cycle.py`，运行独立数值检查、输出等待期间的稳定性检查以及全部公开输出的逐周期比较。`report_paths.py` 在映射连接图中测量寄存状态到 `fifo_full_flag` 的路径，分析过程不改变实际 RTL。

## 运行方法

在仓库根目录执行：

```sh
python test/fifo_write_blocked/run_formal.py \
  --reference cfcc1a95ddcd93625636efc15b8c2b2b1835730f --out build/fifo_write_formal
python test/fifo_write_blocked/run_formal.py --generic \
  --reference cfcc1a95ddcd93625636efc15b8c2b2b1835730f --out build/fifo_write_generic
python test/fifo_write_blocked/run_formal.py --precomputed-watermark 0 \
  --profile v16_n32_b64_c1 \
  --reference cfcc1a95ddcd93625636efc15b8c2b2b1835730f --out build/fifo_write_watermark
python test/fifo_write_blocked/run_four_state.py --out build/fifo_write_four_state
python test/fifo_read_qualification/run_cycle.py --bus-width 32 \
  --reference cfcc1a95ddcd93625636efc15b8c2b2b1835730f --out build/fifo_write_bus32
python test/fifo_read_qualification/run_cycle.py --bus-width 64 \
  --reference cfcc1a95ddcd93625636efc15b8c2b2b1835730f --out build/fifo_write_bus64
python test/fifo_read_qualification/prepare_measurement.py \
  --reference cfcc1a95ddcd93625636efc15b8c2b2b1835730f --out build/fifo_write_measure
python scripts/fpga/open_fpga_synth.py --source-root build/fifo_write_measure/source \
  --case-config build/fifo_write_measure/cases.json --cases reference current \
  --out build/fifo_write_measure/results
python test/fifo_write_blocked/report_paths.py \
  --reference build/fifo_write_measure/results/reference \
  --current build/fifo_write_measure/results/current --out build/fifo_write_paths.json
```

模块资源和接口路径分别测量。完整 SoC 的跨模块组合路径、资源占用及 150 MHz 时序使用相应完整设计报告。
