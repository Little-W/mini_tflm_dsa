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

## 深度卷积流水与并行度

深度卷积每周期向 `PE_COUNT` 个乘加单元发送一组通道。相邻卷积核位置使用
同一组通道时，累加结果直接反馈到下次输入。像素计算结束后，将累加值保存到
独立快照，再并行执行后续像素计算、量化和结果写入。量化结果使用两个缓冲区，
写入模块保存已接收数据并等待 AXI 写入响应。成功响应到达时，待写数据可在同一周期
进入下一次写事务。

`SHARED_QUANT_ENABLE=1` 时，DW 与 GEMM 共用矩阵的十六路量化流水。
完整通道参数从原存储并行读取，累加值、通道掩码与返回标签一起提交。
本地标量配置每周期量化一个通道。窗口返回宽度由 `WINDOW_LANES` 单独设置。
以下两种配置都使用 64 位外部 AXI。

```sh
python3 test/vector_engine/run.py --bus-width 64 --window-lanes 8 --pes 8 --jobs 2 --out build/dw_quant1_pe8
python3 test/vector_engine/run.py --bus-width 64 --window-lanes 16 --pes 16 --shared-quant --jobs 2 --out build/dw_shared_quant_pe16
```

| 配置 | 向量乘法器 | DW 量化来源 | 每周期量化通道数 |
|---|---:|---|---:|
| `PE_COUNT=8`、本地量化 | 8 | 与 Add、Softmax 共用的标量运算单元 | 1 |
| `PE_COUNT=16`、共享量化 | 16 | GEMM 的矩阵量化流水 | 16 |

每个 32 位量化乘法器采用四个 16/17 位部分积。共享配置中，DW 共用 GEMM
现有的乘法、移位、最近偶数舍入与饱和运算，延迟为十二周期。
每个结果槽保存所属通道组的有效通道数；最后一个像素提交共享量化后，
即可开始下一组权重读取。前一组量化返回和写入响应可在此期间继续完成。向量侧的标量运算单元
继续处理 Add 和 Softmax。参数存储增加固定地址读取端口，容量保持不变。
最终面积和时序需通过综合工具测量；展开检查报告乘法运算节点数量。

深度卷积权重以每个卷积核位置为一行，通过一条二维 DMA 命令读取当前通道组的
全部权重，行间距等于输入通道数。偏置、乘数和移位参数的起址等距递增时，
三类参数共用一条三行命令；乘数与移位参数递增存放时，两者共用两行命令。
其他地址布局使用单行命令。每行的最后一次返回更新参数类型，所有地址和有效
数据范围保持由任务配置指定。

功能回归检查连续同通道累加、奇数通道尾部、超过 16 个通道的分组、padding、
stride 2、dilation、量化舍入边界、AXI 随机等待和后续任务恢复。连续输出地址的
字节结果合并为最多 64 字节的写入，统计检查有效输出数和传输数据量，并要求
乘加、量化与写入确实同时工作。权重测试包含 49 个卷积核位置、17 个通道和
跨越 4 KiB 的权重地址，分别在多行读取的首行、页面边界、中间行和末行注入
总线错误。参数测试覆盖等距、非等距、逆序地址，以及各参数行的总线错误和
数值范围检查。错误任务之后立即使用同一地址执行正确任务，并比较全部输出。

32 位和 64 位 AXI 配置分别运行以下命令。`--xilinx` 使用 Yosys 安装目录中
的官方 `DSP48E1` 功能模型，覆盖 Softmax 指数累加器的实际原语配置。

```sh
python3 test/vector_engine/run.py --bus-width 32 --pes 8 --jobs 2 --xilinx --out build/vector_engine_bus32
python3 test/vector_engine/run.py --bus-width 64 --pes 8 --jobs 2 --xilinx --out build/vector_engine_bus64
```

内存服务按总线字节数处理窄读、写字节使能和总线背压，逐字节检查输出范围。
十六字节写入在 32 位和 64 位总线上分别包含四个和两个传输周期。

## 共享权重与部分和存储

`--shared-storage` 设置 `SHARED_STORAGE_ENABLE=1`，要求 `TILE=16`。测试连接生产使用的
`vector_shared_store` 与 `ia_ps_channel_ram`，包含八个 4096 字节的存储块。
当前任务使用一个 IA 存储块保存权重，四个 PS 端口共同保存一行 16 个 INT32 累加值。
权重接口每次读取 128 位，按字节掩码写入；部分和接口每次读取或写入 512 位。
两类读取均在请求上升沿之后返回数据。

共享配置将完成的像素写入 PS 行，下一周期读取该行，再提交量化。
量化直接使用 RAM 保持的返回数据。PE 工作累加寄存器 `acc_buf` 继续处理当前像素，
并服务池化、向量归约与 Softmax。关闭共享配置时，权重和完成像素保存在模块的本地存储中。

```sh
python3 test/vector_engine/run.py --bus-width 64 --window-lanes 16 --pes 16 \
  --shared-quant --shared-storage --cache-line-bytes 128 --cache-sets 32 \
  --jobs 2 --out build/vector_shared_storage_pe16
python3 test/vector_engine/run.py --bus-width 32 --window-lanes 4 --pes 8 \
  --shared-storage --jobs 2 --out build/vector_shared_storage_pe8_local
```

两种共享存储配置使用相同的功能测试，逐元素比较输出，检查权重读取对应的卷积核位置、
有效通道数、完整部分和数据、读取返回周期，以及任务完成前的访问排空。
本地单路量化配置还检查同一 RAM 返回行在多个周期内连续提供各通道输入。
日志中的 `VECTOR_SHARED_STORAGE_CHECK` 分别报告权重写入字节数、读取次数、
部分和写入次数和返回次数。`build.json` 与 `summary.json` 保存共享存储参数及构建信息。

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

每次运行的 `summary.json` 保存实际配置、任务数量、输出数量，以及源码和
可执行文件的 SHA256。功能测试包含 143 个 Add 任务和 273 个 Softmax 任务，
并对深度卷积、池化和其他向量任务检查独立参照结果。

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
python3 test/vector_engine/run_window_error.py --pes 16 --window-lanes 16 --shared-quant --jobs 2 --out build/vector_window_error_pe16
python3 test/vector_engine/inspect_resources.py --pes 8 --window-lanes 8 --out build/vector_resources_pe8
python3 test/vector_engine/inspect_resources.py --pes 16 --window-lanes 16 --shared-quant --out build/vector_resources_pe16
python3 test/vector_shared_quant/run.py --out build/vector_shared_quant
```

定向错误测试在第一个像素已进入待写队列时返回第二个像素的窗口错误。
检查已接收输出完成写入、AXI 响应完成后才报告任务结束，以及后续任务的数值结果。
共享配置另行检查错误发生时仍在量化流水中的请求全部返回，随后才报告任务结束。
测试包括固定等待、随机等待和四种输出字节偏移。独立共享量化测试交替执行
GEMM、DW、GEMM，检查极值、各通道参数、输出标签和固定延迟。

The resource check inspects elaborated multiplication operators and declared
arrays. `--reference /path/to/repository` additionally compares the vector data
array dimensions with another checkout. Test summaries record the source and
executable hashes used by each run.
