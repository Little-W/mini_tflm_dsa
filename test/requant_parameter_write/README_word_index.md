# 参数末次写入资格验证

`check_word_index.py` 读取独立的 `requant_parameter_last.sv` 及其完整模块依赖，对实际参数索引和末次写入条件执行形式证明，并使用 Icarus Verilog 检查四态传播。默认运行 20 种索引位宽、存储组数和 DMA 字位置组合。

```bash
python test/requant_parameter_write/check_word_index.py \
  --source-root . \
  --out build/requant_word_index
```

`--source-root` 默认为当前脚本所属仓库，`--out` 默认为该仓库的 `build/requant_word_index`。脚本使用已安装的 Pyosys、Slang 和 Icarus Verilog。输出包含每种参数配置的形式日志、仿真日志以及 `summary.json`。

## 比较范围

设 `q` 为响应字索引，`w` 为当前 DMA 字位置，`B` 为参数存储组数，`L` 为完整 32 位装载上限。参考表达式先按 `QBUF_IDX_W` 截断 `q + w`，再转换为 32 位索引 `i`，最后以 33 位无符号运算计算 `i + B >= L`。

二组存储配置的第二个 DMA 字直接从加一前的索引计算。低 `min(QBUF_IDX_W, 32)` 位全部为一时，索引回绕为零，末次条件为 `L <= 2`；其他索引计算 `q + 3 >= L`。其余存储组配置保留原有索引转换顺序。

比较器按索引和静态步长确定必要的算术位宽，同时独立检查装载上限的其余高位。三个操作数先形成部分和与各位进位，再使用最终加法的最高进位生成比较结果。验证对 32 位装载上限、索引值和回绕情况均不施加输入限制。

形式配置覆盖 1、3、8、9、16、31、32、36 位索引及 1、2、3、4、8 组存储。四态检查使用固定种子 `20261125`，每种配置执行 30,000 次比较，共 600,000 次；包含索引全零、全一、低 32 位全一、相邻边界值，以及装载上限中的 `X` 和索引中的 `Z`。

## 控制与完整量化检查

脚本同时检查参数装载状态机的更新语句与指定参考源码相同。默认参考提交为 `584233d8`，可通过 `--reference` 指定提交，或使用 `--reference-root` 指定独立源码目录。

完整参数控制器的时序等价与数值检查分别使用以下入口：

```bash
python test/requant_parameter_ports/run_formal.py \
  --source-root . \
  --reference-root /path/to/reference \
  --out build/requant_parameter_ports

python test/requant_time_share/run.py \
  --source-root . \
  --vlen 16 --lanes 2 --reuse 16 --bus 64 --parameter-output 0 --xilinx \
  --out build/requant_time_share_soc
```

控制器证明以全部公开端口和实际寄存器建立对应，完整组合函数参与证明。WS 存储保留实际内容；IS 存储逐个核对参数，并比较全部读写地址、数据、使能及其他驱动端口，读取值可自由变化。相同初始内容和逐拍相同的全部驱动使每个存储地址的状态保持相等。默认 11 组配置同时覆盖参数观察接口启用和关闭两种设置。

完整数值检查覆盖量化输出、参数装载、组间切换、复位和清空事件。当前 SoC 使用 16 次复用、256 行输入容量及 `p_parameter_output=0`。扩展容量配置使用 32 次复用、512 行输入容量；可将上述命令中的 `--reuse` 改为 `32` 运行。

## 装载偏移与偏置推进

`check_control_arithmetic.py` 读取实际的 `load_next_offset` 实例、完整的 `requant_load_advance` 及偏置组推进逻辑，检查完整定宽加法和类型转换。装载偏移始终保留 32 位结果，输入增量先按 `REG_WIDTH` 转换；完整加法函数内部固定零输入进位，通过 `parallel_prefix_add` 的两段部分和推断算术资源，仿真分支保留直接加法的四态结果。

```bash
python test/requant_parameter_write/check_control_arithmetic.py \
  --source-root . \
  --out build/requant_control_arithmetic
```

该检查覆盖 6 种装载位宽和 5 种偏置位宽配置。11 组形式证明均允许全部算术输入自由变化；仿真使用固定种子 `20261125`，共比较 110,000 次综合分支结果和 330,000 次四态结果。`summary.json` 记录生产源码摘要、参数配置、比较次数及各形式日志摘要。

## 验证结果文件

当前独立模块入口的 20 项形式证明和 600,000 次四态比较均通过，结果见 [standalone_validation.json](standalone_validation.json)。

`word_index_validation.json` 保存所测源码和测试脚本的 SHA256、完整参数配置、实际状态比较范围、形式证明及数值结果。输出配置输入的完整表达式与组合深度检查见 `test/output_configuration/README.md`。

| 检查 | 已完成结果 |
| --- | --- |
| 参数末次资格 | 20 组完整输入范围证明，600,000 次四态比较 |
| 装载偏移与偏置推进 | 11 组完整输入范围证明，110,000 次综合分支比较和 330,000 次四态比较 |
| 尾行、尾列与块位置 | 15 组完整输入范围证明，包含实际调用的组合辅助模块 |
| 行结束与复用组结束 | 4 组位宽，160,000 次四态比较 |
| 完整参数控制与存储 | 11 组配置，共 39,935 个时序等价比较位通过 |
| 当前 SoC 量化参数 | 49,737 周期，10,810 行、345,920 个数值输出通过 |
| 扩展容量量化参数 | 75,534 周期，16,954 行、542,528 个数值输出通过 |
