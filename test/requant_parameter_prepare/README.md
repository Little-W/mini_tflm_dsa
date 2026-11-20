# 量化参数准备与配置保存验证

## 当前设计

`vec_requant_full` 在 `init_cfg` 边沿保存原始乘数、原始移位量和输出精度。`pt_product_multiplier_r` 与 `pt_product_amount_r` 保留现有内部名称，由这些已保存的配置组合生成，随后在现有运算输入级采样。

并行分支的 `pt_product_multiplier_s0`、`pt_product_amount_s0` 保持原有采样边沿；分时分支仍在实际发射时由算术通道接收参数。参数有效、DMA 请求、输入接受、输出有效和尾块完成周期保持不变。配置、复位和暂停优先级保持不变。

INT16 乘数采用最近偶数舍入。低半字给出舍入条件，两个字节分别递增；跨字节进位由保护位和低字节全一条件产生。正向饱和保持完整边界。INT8 与 INT16 移位量共用六位模减法，各自保留原有输入范围和特殊值处理。

## 形式验证

`run_formal.py` 从实际 `vec_requant.sv` 提取准备函数、精度寄存和配置更新语句，与提交 `2297cb12` 的对应实现比较。

| 检查 | 配置 | 比较内容 |
|---|---|---|
| 准备函数 | `ENABLE_S16=0/1` | 32 位乘数、32 位移位输入和精度选择的全部已定义组合，比较 39 位准备结果 |
| 配置保存 | `ENABLE_S16=0/1` | 比较 104 位原始参数、精度和准备结果，覆盖任意配置、复位及保持序列 |

四项证明全部通过。输入数值不施加范围限制，包含 `INT_MIN` 和原有定义中的越界移位值。

## 实际模块检查

`run_interface.py` 同时实例化完整当前设计与参考设计，使用 Yosys 的 DSP48E1 功能模型，逐周期比较 19 项公开输出，包括无效周期数据。BUS32 与 BUS64 各运行 256 个场景。测试包含 WS/IS、整张量和逐通道参数、INT8/INT16、参数 DMA 等待、配置与首行同时出现、连续配置、精度切换以及运行期间复位。

生产分时配置另运行 `test/requant_input_stage/run.py` 的实际模块数值测试：16 个元素、2 个算术通道、512 行缓存、64 位总线。该测试使用独立整数参考结果，覆盖零拍和一拍输入寄存、参数等待、整组容量、配置清空和复位恢复。

两种总线宽度分别比较 528,878 个周期；BUS32 比较 209,953 个有效向量，BUS64 比较 208,537 个有效向量。生产分时测试运行 87,139 个周期，核对 627,744 个数值，覆盖 180 组任务、15 组完整容量、7 次配置清空和 6 次复位。

所有 C++ 数值测试启用未定义行为检查。结果中的源码摘要用于确认形式证明、接口检查与综合使用同一份 RTL。

## 原生 RTL 综合

完整模块的参数为 `BUS_WIDTH=64`、`VLEN=16`、`MAX_IA_REUSE=32`、`ENABLE_S16=1`、`p_compute_lanes=2`、`p_input_rows=512`。保留全部公共端口。采用原生 Xilinx 算术映射，ABC9 的六种 LUT 输入宽度成本均为 1。

| 项目 | `2297cb12` | 当前设计 |
|---|---:|---:|
| 逻辑 LUT | 3980 | 3981 |
| FF | 3418 | 3379 |
| DSP48E1 | 10 | 10 |
| RAMB18E1 | 19 | 19 |
| RAMB36E1 | 0 | 0 |
| 参数寄存器至实际消费者的最长路径 | 9 | 9 |
| 完整模块最长寄存器路径 | 15 | 15 |

R8 整机中的 18 级路径包含顶层参数地址加法和寄存前的准备函数。当前准备函数位于原始配置寄存器之后，顶层参数地址在该寄存边沿结束。完整量化模块剩余的 15 级路径涉及装载范围及完成判断，完整路径列表保存在测量结果中。

该测量未进行额外算术单元 DSP 替换、物理 LUT 合并或布局。整机组合路径及 150 MHz 时序应以集成后的器件报告为准。

## 运行

需要 Python 3、带 `read_slang` 的 Yosys Python 包 `pyosys`、Verilator 和 C++ 编译器。工具应已加入当前环境的 `PATH` 与 Python 模块路径。

```sh
python test/requant_parameter_prepare/run_formal.py \
  --out /tmp/requant_parameter_prepare/formal

python test/requant_parameter_prepare/run_interface.py \
  --out /tmp/requant_parameter_prepare/interface \
  --verilator verilator-modern --jobs 1 --xilinx

python test/requant_input_stage/run.py --simulation-only \
  --out /tmp/requant_parameter_prepare/serial \
  --verilator verilator-modern --vlen 16 --lanes 2 --reuse 32 --bus 64 --xilinx

python test/requant_parameter_prepare/measure.py \
  --out /tmp/requant_parameter_prepare/mapping --lanes 2
```

各步骤顺序执行。接口测试保留可执行文件并删除可重新生成的编译目录；映射网表采用 gzip 保存。`measurement.json` 保存正式结果与源码摘要。
