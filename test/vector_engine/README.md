# Vector engine verification

`run.py` builds the production vector engine, DMA arbiter, window descriptor
queue, image frontend, shared cache, and AXI engines. Independent integer
references check DW, Pool, vector operations, Add, Softmax, and nearest-even
requantization. The memory scoreboard checks every byte, including bytes
outside the output tensor.

Run functional tests with both supported execution widths used by the design
documentation:

```sh
python3 test/vector_engine/run.py --pes 1 8 --jobs 2 --out build/vector_engine
```

32 位和 64 位 AXI 配置分别运行以下命令。`--xilinx` 使用 Yosys 安装目录中
的官方 `DSP48E1` 功能模型，覆盖 Softmax 指数累加器的实际原语配置。

```sh
python3 test/vector_engine/run.py --bus-width 32 --pes 8 --jobs 2 --xilinx --out build/vector_engine_bus32
python3 test/vector_engine/run.py --bus-width 64 --pes 8 --jobs 2 --xilinx --out build/vector_engine_bus64
```

内存服务按总线字节数处理窄读、写字节使能和总线背压，逐字节检查输出范围。
十六字节写入在 32 位和 64 位总线上分别包含四个和两个传输周期。

## 结果写入选择与参数存储

串行结果先共享字节数据与地址选择，再由各存储项产生写使能；Hadamard 的
并行结果和池化结果保持独立写入。`run_result_write.py` 从参照提交与当前
RTL 提取实际组合逻辑，覆盖全部状态编码、操作码、写入来源重叠和通道尾部。

```sh
python3 test/vector_engine/run_result_write.py --out build/vector_result_write
```

在 `TILE=16`、`PE_COUNT=8` 的独立寄存输入/输出测量中，结果写入逻辑
使用 876 个逻辑 LUT、444 个寄存器，寄存器之间最长组合路径为 6 个单元。
相同测量条件下的参照实现使用 1,319 个逻辑 LUT、444 个寄存器和 7 个单元。
两种实现的写入时钟边沿和来源优先顺序一致。

量化参数的 regfile 状态证明、不同总线写入检查和资源测量见
[`test/vector_params`](../vector_params/README.md)。完整向量回归同时检查这些
存储修改对算术结果、DMA 地址范围和任务执行周期的影响。

使用官方 `DSP48E1` 功能模型的两种总线回归结果如下。每种配置都包含
143 个 Add 任务和 273 个 Softmax 任务，全部任务逐项执行统计与参照实现一致。

| 总线宽度 | 任务数 | 检查输出数 | 总执行周期 |
|---|---:|---:|---:|
| 32 | 592 | 168,972 | 2,937,907 |
| 64 | 592 | 170,551 | 2,952,522 |

Run the default eight-PE performance suite:

```sh
python3 test/vector_engine/run.py --pes 8 --perf --jobs 2 --out build/vector_performance
```

The functional suite applies random AXI delays and checks allocation bounds,
4 KiB boundaries, stable payloads under backpressure, error completion,
subsequent task execution, destination tags, and input-slot ownership. Both
PE configurations must accept multiple outstanding window requests. The
eight-PE configuration also checks simultaneous request and response activity.

## Strided-window study

```sh
python3 test/vector_engine/run.py --pes 8 --perf --window-study --jobs 2 \
  --out build/vector_window_study
```

This suite uses six aligned DW shapes. Its 32-bit memory service makes the
first read response available three cycles after an address handshake and returns successive
beats of a burst every two cycles, and leaves at least three cycles between the
last response of one burst and the first response of the next. Every reported
cache miss is classified when the demand request is accepted. Output checking
and input/output bounds are the same as in the functional suite.

## Error and resource checks

```sh
python3 test/vector_engine/run_window_error.py --jobs 2 --out build/vector_window_error
python3 test/vector_engine/inspect_resources.py --out build/vector_resources
```

The directed error test schedules a terminal window error while an output
write receives its grant. It checks the complete write and response drain,
idle completion, and the numerical output of the following task, with fixed
and random AXI waits and all four output byte offsets.

The resource check inspects elaborated multiplication operators and declared
arrays. `--reference /path/to/repository` additionally compares the vector data
array dimensions with another checkout. Test summaries record the source and
executable hashes used by each run.
