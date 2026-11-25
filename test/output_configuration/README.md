# 输出模块配置与组合路径检查

`npu_output_pipeline` 在配置采样边沿保存偏置组起点、末组起点和有效行数。配置组合逻辑并行计算目标行数减一、执行行数高段减一和低段差值；尾组判断只选择完整计算结果。`requant_parameter_last`、`requant_group_last`、`requant_load_advance` 和 `requant_group_difference` 分别保存完整参数末次资格、复用组结束、加载偏移加法和组内行数差值的组合边界。

这些函数保留全部定宽转换、回绕结果和配置保存边沿。量化状态机、DMA 握手、缓存容量与计算流水周期保持原有行为。算术资源由普通 RTL 表达式推断。

## 两种完整模块配置

| 参数 | 当前 SoC 配置 | 默认扩展容量 |
| --- | ---: | ---: |
| `p_bus_width` | 64 | 64 |
| `p_dim_count_width` | 29 | 16 |
| `p_ia_reuse_num_max` | 16 | 32 |
| `p_requant_max_ia_reuse` | 16 | 32 |
| `p_is_bias_row_w` | 8 | 9 |
| `p_is_bias_valid_w` | 9 | 10 |
| `p_requant_compute_lanes` | 2 | 2 |
| `p_oa_fifo_banks` | 32 | 32 |
| `p_oa_s16_fifo_banks` | 4 | 4 |
| 量化输入缓存行数 | 256 | 512 |

两种配置均使用 32 位地址和执行尺寸。输出模块内部的量化实例设置 `p_parameter_output=0`。当前 SoC 的计数宽度由 `NPU_ADDR_WIDTH=32` 推导为 29 位，IA 复用次数由 7×8192 存储配置和 16 位数据宽度推导为 16。

## 完整表达式验证

```bash
python test/output_configuration/check_configuration.py \
  --source-root . \
  --reference-root /path/to/reference \
  --out build/output_configuration
```

参考目录可使用提交 `568f8e22` 的独立工作目录。脚本读取实际配置算术及完整辅助模块，比较掩码、整组基址、尾行数、末组基址、首组有效行数和范围判断。独立数学表达式显式保留每次类型转换与结果截断。

10 组形式证明覆盖 1、4、8、16、32、35、64 位结果宽度，并包含当前 SoC 的 9 位目标行数和扩展容量的 10 位目标行数。完整 32 位执行尺寸及所有目标行数均可自由变化。配置寄存器的复位、使能和更新表达式逐项检查。固定种子 `20261125` 的四态仿真共比较 300,000 次。

量化验证入口分别为 `test/requant_parameter_write/check_word_index.py`、`check_control_arithmetic.py`、`test/requant_tail_count/run_formal.py` 和 `test/requant_parameter_ports/run_formal.py`。各脚本均支持指定固定源码目录，验证摘要记录所读取文件的 SHA256。

## 完整模块映射与路径

```bash
python scripts/fpga/open_fpga_synth.py \
  --source-root . \
  --case-config test/output_configuration/cases.json \
  --cases output_default output_production \
  --out build/output_mapping \
  --require-register-path-limit

python test/output_configuration/analyze_interfaces.py \
  --netlist build/output_mapping/output_production/mapped.json \
  --pre-lut build/output_mapping/output_production/pre_lut.il \
  --out build/output_mapping/output_production/interface_paths.json
```

`metrics.json` 统计完整映射模块的资源和寄存器间组合路径。接口分析仅在分析图中加入输入与输出边界标记，分别计算输入到寄存器、寄存器到输出和输入到输出的最长组合路径。边界标记不参与资源统计。

`validation.json` 保存两种配置的完整模块结果、源码摘要和网表摘要。逻辑 LUT、分布式 RAM LUT、移位寄存器 LUT 和 `INV` 单元分别统计。组合级数用于检查逻辑结构；150 MHz 时钟要求由目标器件的布局布线时序报告核实。

| 测量项目 | 当前 SoC 配置 | 默认扩展容量 |
| --- | ---: | ---: |
| 逻辑 LUT | 6,155 | 5,879 |
| 分布式 RAM LUT | 120 | 120 |
| 移位寄存器 LUT | 14 | 14 |
| `INV` 单元 | 299 | 286 |
| 触发器 | 3,079 | 2,961 |
| DSP48E1 | 32 | 32 |
| RAMB36E1 / RAMB18E1 | 4 / 27 | 4 / 27 |
| 寄存器间最长组合逻辑 | 10 级 | 10 级 |
| 输入到寄存器最长组合逻辑 | 9 级 | 10 级 |
| 寄存器到输出最长组合逻辑 | 7 级 | 7 级 |
| 输入到输出最长组合逻辑 | 4 级 | 4 级 |

写回分组步长的完整控制器证明、四态检查及资源比较见 `test/oa_writer_group_step/README.md`。
