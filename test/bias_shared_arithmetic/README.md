# 偏置共享地址算术

`bias_loader_ctrl` 在互斥状态中共用一个完整位宽的加减单元，完成最后分组位置、DMA 首地址、尾块地址、下一分组索引和剩余分块数的计算。`p_dsp_split_width` 将现有加法器划分为两个部分和；当前配置为 16 位低段和 16 位高段。普通 RTL 加法由综合工具推断算术资源，结果修正保留完整进位和原有截断规则。

全部控制状态、复位条件、寄存器写入边沿及 DMA 握手保持相同。较大位宽由公共加法器的参数条件选择分组进位实现。

## 当前 SoC 配置

| 参数 | 值 |
| --- | ---: |
| `SIZE` | 16 |
| `DATA_WIDTH` | 32 |
| `BUS_WIDTH` | 64 |
| `REG_WIDTH` | 32 |
| `COUNT_WIDTH` | 29 |
| `GROUP_BLOCKS_MAX` | 16 |

`npu_top` 的当前共享存储配置提供 32 个 IA 分块，`npu_matrix_engine` 将 IA 最大复用数设为 16，IS 模式下偏置分组容量随之设为 16。

## 完整模块结果

对照提交为 `17dda6a11cd55ea470712335f2b5cfcfca4b4bd4`。两侧使用相同参数、完整依赖和综合流程：256 个模块一批、组合叶模块隔离及逐模块证明、原生组合辅助模块定义复用。全部公开端口参与分析。

| 项目 | 对照版本 | 当前版本 |
| --- | ---: | ---: |
| 逻辑 LUT | 1,337 | 1,307 |
| INV | 14 | 14 |
| FF | 1,148 | 1,148 |
| CARRY4 | 48 | 40 |
| DSP48E1 | 0 | 1 |
| RAMB36E1 | 1 | 1 |
| RAMB18E1 | 0 | 0 |
| 寄存器到寄存器最长组合级数 | 10 | 10 |
| 输入到寄存器最长组合级数 | 10 | 10 |
| 寄存器到输出最长组合级数 | 5 | 6 |
| 输入到输出最长组合级数 | 3 | 3 |

两个完整连接图均通过检查。LUT 数为布局前的映射单元数，150 MHz 仍需结合目标器件的布局布线时序检查。上表描述完整偏置加载器边界内的结果，整机路径另行包含上游模块的组合逻辑。

## 功能与周期检查

- `run_formal.py` 检查 8 组完整加载器配置，覆盖 8、16、32、64 位寄存器宽度，1、8、12、29、32、64 位计数宽度，以及 32、64、128 位总线。9,411 个位关系全部通过无限时序等价证明。外部输入没有范围或握手假设。
- 形式模型保留控制器、缓冲区和 WS 向量缓存的实际 RTL。两侧存储返回使用每周期共用的任意 64 位输入；读写地址、写入数据、字节掩码和读写使能均作为公开比较端口。内部对应只允许真实寄存器输出，组合信号全部排除。
- `check_four_state.py` 对完整控制器的所有公开输出和寄存器进行严格四态比较。4 组配置共完成 65,544 个周期，包含全部配置位宽的随机输入、被采样的未知配置、X/Z 握手和 X/Z 复位。
- `run_numeric.py` 对两侧运行相同的 392 项实际存储事务，覆盖 WS、IS、32/64 位总线和 1/2/4/8/16/32 分块容量。该事务模型使用 `SIZE=16`、`REG_WIDTH=32`、`COUNT_WIDTH=12`。全部数值检查及 DMA 请求计数通过；每项周期数完全相同，各用例周期合计均为 193,571。
- 公共加法器使用与 [器件映射检查](../parallel_prefix_dsp/README.md) 完全相同的源码。32 位、可变输入进位配置的实际 DSP 映射已对完整官方器件模型完成全部 33 位输出的无限时序等价证明。

配置、源文件摘要及结果记录于 [validation.json](validation.json)。

## 复现

在仓库根目录执行，Python 环境需要 Pyosys/Slang，仿真需要 Icarus Verilog 和支持 C++20 的 Verilator。

```bash
BIAS_OUT=/tmp/bias_shared_arithmetic
python test/bias_shared_arithmetic/run_formal.py --out "$BIAS_OUT/formal"
python test/bias_shared_arithmetic/check_four_state.py --out "$BIAS_OUT/four_state"
python test/bias_shared_arithmetic/run_numeric.py --out "$BIAS_OUT" --jobs 1
python test/bias_shared_arithmetic/prepare_measurement.py --out "$BIAS_OUT/inputs"

for version in reference current; do
  python scripts/fpga/open_fpga_synth.py \
    --source-root "$BIAS_OUT/inputs/$version" \
    --case-config "$BIAS_OUT/inputs/cases.json" --cases "$version" \
    --out "$BIAS_OUT/mapping" --lock-file "$BIAS_OUT/mapping.lock" \
    --abc9-batch-size 256 --abc9-isolate-leaves --native-combinational-helpers \
    --require-register-path-limit --max-register-path-cells 10
  python test/output_configuration/analyze_interfaces.py \
    --top bias_loader \
    --netlist "$BIAS_OUT/mapping/$version/mapped.json" \
    --pre-lut "$BIAS_OUT/mapping/$version/pre_lut.il" \
    --out "$BIAS_OUT/mapping/$version/interface_paths.json"
done
```

所有新脚本均接受 `--source-root` 和 `--reference`。数值脚本的 `--resume` 仅复用源文件摘要和仿真可执行文件摘要均匹配的已通过结果；`--verilator` 可指定本机工具路径。综合参数同时写入明确的 `-G` 选项。
