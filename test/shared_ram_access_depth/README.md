# 共享存储访问控制的时序检查

## 实现

`npu_top` 在任务接收后保存共享存储配置请求和 IA 存储块数量，下一周期将配置交给共享 RAM 与 `vector_shared_store`。任务接收周期和配置周期都禁止物理读写。矩阵任务与向量任务共用该配置寄存级。

`ia_ps_channel_ram.i_access_enable` 默认为 `1`。顶层使用该输入控制物理访问；请求地址译码、端口优先选择及碰撞判断先独立计算，再将访问条件合并到读写使能和故障接收条件。IA 端口零保持优先，越界与同地址读写仍按原规则处理。

## 形式检查

`run_formal.py` 直接使用当前源码和 `--baseline-ref` 指定版本的源码。参考实现先屏蔽请求输入，当前实现使用独立的访问控制输入。测试比较全部配置状态、容量故障、读数据返回选择，以及每个物理存储器的读写使能和有效命令的地址、掩码、写数据。

物理 RAM 在形式检查中使用固定返回值，存储内容不进入 SAT。全部有效存储命令以及对应返回选择逐位相同，因此两份实现对相同初始存储内容执行相同操作。形式检查使用二态时序归纳，输入无额外约束。

默认执行四种容量配置和两种共享写数据选择参数，共八组检查：

```bash
python test/shared_ram_access_depth/run_formal.py \
  --baseline-ref dde5e7c9 \
  --out build/shared_ram_access_depth/formal
```

实际存储内容、字节掩码、配置切换、越界和碰撞使用已有测试入口验证：

```bash
python test/ps_channels/run_memory.py \
  --profiles 2048:6 8192:7 8192:9 \
  --cycles 20000 \
  --out build/shared_ram_access_depth/memory
```

## 局部综合

测量使用七个 8192 字节存储块，启用共享写数据选择。两份设计使用相同的输入和输出测量寄存器，完整保留物理存储器。

```bash
python test/shared_ram_access_depth/prepare_measurement.py \
  --baseline-ref dde5e7c9 \
  --out build/shared_ram_access_depth/measurement

python scripts/fpga/open_fpga_synth.py \
  --source-root build/shared_ram_access_depth/measurement/source \
  --case-config build/shared_ram_access_depth/measurement/cases.json \
  --cases reference current \
  --lock-file /tmp/npu_synthesis_20261121.lock \
  --out build/shared_ram_access_depth/measurement/synthesis
```

| 项目 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT 数 | 1987 | 1989 |
| 触发器数，含测量寄存器 | 1871 | 1871 |
| RAMB36 数 | 26 | 26 |
| DSP 数 | 0 | 0 |
| 整个测量模块的最长寄存器间组合路径 | 8 | 8 |
| 访问控制至容量故障寄存器 | 8 | 2 |
| 访问控制至物理 RAM 写使能 | 6 | 4 |
| 访问控制至全部寄存器和 RAM 端点的最大级数 | 8 | 4 |

上述计数来自开源工具的器件映射。完整 SoC 的组合级数由整机映射单独检查，150 MHz 由布局布线后的时序报告确认。

## 完整任务验证

`test/fpga_integration/run.py` 验证生产参数下的 38 个矩阵与卷积任务，共 11118 个 INT32 结果检查。

`test/vector_engine_cosim/run.py` 验证生产驱动、AXI-Lite 顶层与外部存储模型。固定延迟和随机延迟各执行 104 个案例、52214 个输出检查和 99 条硬件命令。测试包含矩阵与向量任务交替、IA 存储分配切换、五类错误处理及后续任务恢复。

```bash
python test/fpga_integration/run.py \
  --out build/shared_ram_access_depth/fpga --jobs 2

python test/vector_engine_cosim/run.py \
  --size 16 --pe-count 8 --bus-width 64 \
  --bank-bytes 8192 --bank-count 7 --cache-bytes 4096 --pcr \
  --target generic --out build/shared_ram_access_depth/vector_generic --jobs 2

python test/vector_engine_cosim/run.py \
  --size 16 --pe-count 8 --bus-width 64 \
  --bank-bytes 8192 --bank-count 7 --cache-bytes 4096 --pcr \
  --target asic --out build/shared_ram_access_depth/vector_asic --jobs 2

python test/shared_ram_access_depth/collect_report.py \
  --formal build/shared_ram_access_depth/formal \
  --memory build/shared_ram_access_depth/memory \
  --measurement build/shared_ram_access_depth/measurement \
  --fpga build/shared_ram_access_depth/fpga \
  --cosim build/shared_ram_access_depth/vector_generic build/shared_ram_access_depth/vector_asic \
  --out test/shared_ram_access_depth/measurement.json
```

结果摘要保存实际源码 SHA256、测试摘要 SHA256、映射结果 SHA256 以及对应访问控制路径。
