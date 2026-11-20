# 平均池化倒数表同步读取

`vector_engine` 在每个时钟边沿读取完整精度倒数表，并在原有 `AVG_START`
乘法采样边沿使用读取结果。默认 `POOL_MAX_TAPS=256` 时，表包含 257 个
18 位常量，第 0 项为零，其余各项为 `ceil(2^17 / denominator)`。
FPGA 使用标准同步 ROM 写法及 `rom_style="block"` 属性，ASIC 使用静态
常量连接和同一读取寄存器。

## 周期与精度

状态机进入 `AVG_START` 前已经保持 `valid_taps`。第一次计算经过
`QUANT_INIT`，后续通道经过现有的平均池化处理状态。同步读取在乘法消费
之前完成，不增加任务状态、输出等待周期或乘法流水级。原有乘法、整数
修正和舍入表达式均保持。

控制证明直接保留生产状态机、`valid_taps` 更新及新增的地址采样状态，
将其他数据寄存器替换为任意值，证明：

```systemverilog
rst_n && state == AVG_START
    -> valid_taps == previous_edge(valid_taps)
```

证明对外部输入不施加限制，覆盖复位、DMA 错误导致的取消、背压以及后续
通道状态转换。表内容的独立检查覆盖分母 0、1、256、越界地址和四态地址。

## 检查结果

| 检查 | 范围 | 结果 |
| --- | --- | --- |
| ROM 时序等价 | `POOL_MAX_TAPS=1,3,49,255,256,257`，FPGA 和 ASIC 分支，共 12 项 | 通过 |
| 生产状态机归纳 | BUS32、BUS64，实际状态与分母更新，无外部输入限制 | 通过 |
| 四态地址穷举 | 每个分支 `4^9=262144` 个地址，共 524288 次比较 | 通过 |
| 映射内容与端口 | 4626 个有效数据位、255 个越界字、全部地址和输出连接、时钟与只读控制 | 通过 |
| 双完整引擎比较 | 592 项任务，全部 35 个公开端口逐周期比较，含无效输出周期 | 通过 |
| 独立整数参考 | 168601 个数值输出；任务周期合计 2979488 | 通过 |
| 容量识别 | 95 项容量单元测试、12 项真实 ROM AST 检查、生产 NPU 展开 | 通过 |

双引擎检查使用生产 DMA、8 个向量 PE、64 位总线以及官方 Xilinx DSP
功能模型。原始测试集包含深度卷积、S8/S16 池化、Add、Softmax、随机背压、
读取和写入错误以及配置边界。两个引擎共享同一组输入，各自保留全部状态。

## 独立模块资源

以从生产源码提取的倒数表进行 `synth_xilinx` 综合：

| 资源 | 组合读取参考实现 | 同步读取实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 90 | 0 |
| 普通触发器 | 0 | 0 |
| RAMB18E1 | 0 | 1 |
| DSP48E1 | 0 | 0 |

18 位读取状态由 RAMB18E1 同步端口实现。该表中数值表示独立模块映射资源；
整个 SoC 的物理 LUT 数量由对应的完整布局测量记录。

默认配置的只读表容量为 `257 × 18 = 4626 bit`，物理块 RAM 容量为
18432 bit。原有逻辑缓冲容量为 994508 bit，加入只读表后为 999134 bit，
即 124891.75 字节；同时计入 18 位读取状态后为 124894 字节，低于
128 KiB。向量 PE 数量、缓存数组长度和数据格式保持。

生产 NPU 的容量程序从实际展开结果识别这 4626 位只读表，并以
`vector_pool_reciprocal_rom` 单独分类，计入数组容量预算。原有所有缓存分类
及位数保持。`capacity_measurement.json` 保存生产层次、完整容量分类和
参数检查结果。

## 复现

需要 Python、pyosys/Yosys-slang、Icarus Verilog 和 Verilator。工具环境
准备完成后，在仓库根目录执行：

```bash
task_out=/tmp/vector_pool_reciprocal
python test/vector_pool_reciprocal/run_formal.py --out "$task_out/formal"
python test/vector_pool_reciprocal/run_control.py --out "$task_out/control32" --bus-width 32
python test/vector_pool_reciprocal/run_control.py --out "$task_out/control64" --bus-width 64
python test/vector_pool_reciprocal/run_four_state.py --formal-out "$task_out/formal" --out "$task_out/four_state"
python scripts/fpga/open_fpga_synth.py --case-config "$task_out/formal/cases.json" --cases reference current --out "$task_out/synthesis"
python test/vector_pool_reciprocal/check_mapped.py --mapped-case "$task_out/synthesis/current" --out "$task_out/mapped_check.json"
python test/vector_pool_reciprocal/run_numeric.py --out "$task_out/dual_numeric64" --bus-width 64 --verilator verilator-modern
python test/vector_pool_reciprocal/run_capacity.py --out "$task_out/capacity_rom" --verilator verilator-modern
python -m unittest discover -s test/capacity -p 'test_*.py' -v
python test/capacity/check_elaboration.py --config config/npu_fpga.mk --output-root "$task_out/capacity_npu" --verilator verilator-modern
```

`run_formal.py` 和 `run_numeric.py` 默认从提交 `e03a7421` 读取参考引擎。
`measurement.json` 保存当前实现的源码摘要、参数、检查数量和资源测量。
