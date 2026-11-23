# ASIC 同步存储与量化参数配置

`regfile` 在定义 `ASIC_SRAM` 且参数适合 SRAM 时，通过项目现有的 `smic40_sram_1r1w` 封装实现同步存储。公开接口保持一个时钟周期的同步读取、读取未使能时保持输出、独立写入掩码，以及同一周期同一地址读写返回写入前内容的行为。

## 存储结构

每个写入分段使用独立 SRAM 封装，每个读取端口具有相应存储副本。逻辑深度不超过 384 时选择 128 行宏，更大深度选择 1024 行宏。宏映射要求同步读取、深度至少 32、数据位宽能够按写入分段整除。容量利用率为逻辑存储位数除以所有宏的物理位数，包含写入分段的宽度填充、深度填充和读取端口复制。128 行宏要求利用率至少 50%，1024 行宏要求至少 25%；其余参数使用行为级存储。此门限是根据现有宏面积数据选择的启发式值，实际面积和时序需要综合确认。

写入缓冲在接收写入后的下一个边沿提交 SRAM。读取请求访问已经接收但尚未提交的写入时，读取端保存对应分段的数据并关闭该 SRAM 的物理读取。各分段分别决定读取或转发，因此部分写入保留其他分段的数据，也避免宏端口同时读写同一物理地址。接口读取当前边沿的新写入地址时，仍然返回该边沿写入前的逻辑内容。

存储器没有复位端口，写入缓冲也不会因上层任务复位而丢弃已接收的写入。同步读取未使能时保持输出；非法读取地址返回未知值，非法写入地址不修改逻辑存储。四态测试覆盖未知控制、地址、掩码和数据，以及连续写入、最后一次写入后立即读取和部分写入转发。

| 实际使用 | 位宽 × 深度 | 写入分段 | 读取端口 | SRAM 数量 |
| --- | ---: | ---: | ---: | --- |
| `kernel_loader_buffer` 的每一列 | 16 × 48 | 16 | 1 | 行为级存储 |
| `bias_loader` 存储 | 64 × 512 | 8 | 1 | 8 个 `RAMTP1024X16` |
| 每组 IS 乘法参数 | 32 × 256 | 32 | 1 | 4 个 `RAMTP128X16` |
| 每组 IS 移位量参数 | 7 × 256 | 7 | 1 | 行为级存储 |

不定义 `ASIC_SRAM` 时，预处理后的行为级 `regfile` 与参考实现相同；FPGA 的存储推断继续使用原有 RTL。

## 量化参数观察输出

`vec_requant` 提供 `p_parameter_output`，默认值为 `1'b1`。启用时，`quant_multiplier_lane` 和 `quant_shift_lane` 保持完整的参数观察功能。设置为 `1'b0` 时，这两个观察输出为零，专门服务这些输出的原始 IS multiplier、shift 表不展开。量化运算实际使用的 product multiplier、product amount 和 WS 参数表保持完整。

`npu_top.u_vec_requant` 将此参数设置为 `1'b0`。顶层的数值输出、参数写入协议、背压和运算周期保持一致。

## 验证结果

验证包括逐周期功能比较、宏数量检查、存储归纳证明以及量化接口等价检查。每次运行的结果和源码摘要保存在指定的输出目录中。

存储归纳证明选择任意固定合法地址，比较全部数据位的逻辑内容与物理内容加写入缓冲的关系，并证明读取采样、输出保持和宏端口冲突条件。生产读取与写入输入不增加约束。二态归纳使用共同初值；未初始化存储和未知输入的行为由四态比较检查。

量化接口证明比较实际运算输出、控制状态和存储器读写端口。可独立处理的单读端口存储接收任意相同返回数据，并核对两侧存储参数；流水线数组和多端口 WS 存储保留实际状态。两侧均按顶层连接检查实际消费者，直接比较观察参数启用和关闭时的运算与控制。原始参数输出数值由 `test/requant_parameter_read` 单独检查。

`sram_model.sv` 实现同步功能模型，并在宏同时读写相同物理地址时终止测试。它用于功能比较；库时序弧与工艺面积由 DC 使用实际库文件分析。

## 运行方法

在仓库根目录运行。依赖 Python、Icarus Verilog，以及带 Slang 前端的 Yosys Python 接口；脚本通过 `scripts/fpga/open_fpga_synth.py` 调用 Yosys。

```sh
python test/asic_regfile/run.py --out build/asic_regfile
python test/asic_regfile/run_formal.py --out build/asic_regfile_formal
python test/asic_regfile/run_parameter_outputs.py \
  --out build/asic_parameter_outputs
```

每个脚本在输出目录保存本次源码副本、参数、日志和 `summary.json`。`run.py --simulation-only` 可单独执行四态比较。`run_formal.py --profiles` 使用 `width:depth:write_unit:read_ports`；`run_parameter_outputs.py --profiles` 使用 `VLEN:BUS_WIDTH:compute_lanes:MAX_IA_REUSE`。

## 面积计算

利用率门限的面积与时序影响通过目标工艺库的 DC 综合报告确认。
