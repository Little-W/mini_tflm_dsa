# 输出模块算术与控制路径

## RTL 结构

`npu_output_pipeline` 使用分组进位计算偏置组的推进地址。`vec_requant` 保留完整的组范围、剩余字数和装载偏移结果，并通过普通加法表达式推断并行算术资源。参数末次写入判断同时处理索引截断、回绕和装载上限的高位。

`requant_round_add` 将三十五位量化加法划分为低段和高段，分别形成部分和，再并行计算舍入进位与高段修正。量化通道保留七个使能时钟沿的延迟，复位、清空和暂停行为保持相同。

FIFO 的当前写入位置及后续两个位置并行计算阻塞状态，写入完成只选择相应结果。银行计数更新将释放块数的部分积、当前数量和同周期写入增量合并，最后传播一次算术进位。分块行列乘积使用进位保存归并和分组前缀加法。

写回控制器将复用数量译为七位系数，通过完整定宽乘法计算组步长；配置边沿及运行周期保持相同。

## 综合结果

`cases.json` 分别定义 `output_default` 和 `output_production`，均包含全部公开端口，以及 `SYNTHESIS=1` 和 `XILINX_FPGA=1`。默认扩展容量配置采用 16 位分块计数、32 次 IA/量化复用和 9/10 位偏置索引/行数；当前 SoC 配置采用 29 位分块计数、16 次复用和 8/9 位偏置索引/行数。两者均为 64 位总线、2 个量化计算通道、32 个 INT8 输出银行和 4 个 INT16 输出银行。

以下完整模块结果由 Yosys 0.71+40、Slang 和 `synth_xilinx` 的 XC7 ABC9 流程生成。当前配置与源码摘要见 `test/output_configuration/validation.json`。

| 项目 | 默认扩展容量 | 当前 SoC 参数 |
| --- | ---: | ---: |
| 逻辑 LUT | 5,879 | 6,155 |
| 分布式 RAM LUT | 120 | 120 |
| 移位寄存器 LUT | 14 | 14 |
| `INV` 单元 | 286 | 299 |
| 触发器 | 2,961 | 3,079 |
| DSP48E1 | 32 | 32 |
| RAMB36E1 | 4 | 4 |
| RAMB18E1 | 27 | 27 |
| 寄存器之间的最长组合逻辑 | 10 级 | 10 级 |
| 输入到寄存器的最长组合逻辑 | 10 级 | 9 级 |
| 寄存器到输出的最长组合逻辑 | 7 级 | 7 级 |
| 输入到输出的最长组合逻辑 | 4 级 | 4 级 |

寄存器路径分析包含数据端口和同步控制端口，并根据 DSP 内部寄存器参数识别时钟边界。当前图中没有未分类单元或未访问的组合节点。

接口路径通过仅用于分析的端口边界标记计算。上述级数是结构测量；150 MHz 的时钟检查使用目标器件的布局布线延迟。

本目录的 `measurement.json` 保存两份按源文件摘要标识的默认扩展容量快照，其中输出主模块与量化控制模块对应提交 `568f8e22`。文件中明确记录参数、模块版本和各源文件摘要。两种当前配置的结果及复现入口统一见 `test/output_configuration/README.md`。

```bash
python scripts/fpga/open_fpga_synth.py \
  --source-root . \
  --case-config test/output_timing/cases.json \
  --cases output_default output_production \
  --require-register-path-limit \
  --out build/output_timing
```

## 功能与周期检查

| 检查范围 | 已完成结果 |
| --- | --- |
| 舍入加法器 | 8 组参数的完整输入范围证明、320,000 次四态比较，映射后全部 35 个输出位等价 |
| 量化结果位宽 | 68 个自由输入位的形式证明、280,832 次四态比较 |
| 量化计算通道 | 5 种 RTL 或映射后配置，各 1,057,912 周期、850,859 次输出比较；延迟均为 7 个使能时钟沿 |
| FIFO 完整状态和存储端口 | 10 组参数的时序归纳证明通过，覆盖 1 至 64 个银行、32/64 位总线和两种存储排列 |
| FIFO 乘积与行比较 | 64 组完整输入范围证明、6,291,460 次四态比较通过 |
| 当前 SoC 量化参数 | 49,737 周期、10,810 行输出、345,920 个数值；168 组、464 次 DMA 命令、7 次清空和 6 次复位通过 |
| 扩展容量量化参数 | 75,534 周期、16,954 行输出、542,528 个数值；170 组、608 次 DMA 命令、7 次清空和 6 次复位通过 |

量化参数索引和完整控制器的附加验证见 `test/requant_parameter_write/README_word_index.md`。所有修改保持数据精度、存储容量和外部交互周期。

主要复现入口：

```bash
python test/requant_compute_lane/check_round_add.py --out build/round_add
python test/requant_compute_lane/run_width.py --out build/requant_width
python test/fifo_release_selection/run_formal.py \
  --source-root . --reference aa92d51a --out build/output_fifo_formal
python test/fifo_tile_arithmetic/run_comb.py --source-root . --out build/output_fifo_math
python test/requant_time_share/run.py \
  --source-root . --vlen 16 --lanes 2 --reuse 16 --bus 64 --parameter-output 0 --xilinx \
  --out build/output_quantization
```
