# 量化参数装载命令资格

`vec_requant` 在现有 DMA 命令准备周期保存 `cmd_has_more_r`。该字段与命令地址、突发长度和参数字数同时生成，等待 DMA 许可及接收响应期间保持不变。最后一个响应字到达时，状态机直接使用该字段决定推进偏移、切换参数类型或结束装载。

配置接收和复位清除命令资格。命令的发送周期、响应字计数、乘数与移位参数顺序、参数有效周期及量化输出周期保持一致。

## 算式与位宽

对于三十二位无符号总量 `need` 和偏移 `offset`，实际突发字数为：

```text
remaining = max(need - offset, 0)
chunk = min(remaining, VLEN)
```

当 `offset < need` 时，`offset + chunk <= need`，相加结果不会超出三十二位范围，因此 `(offset + chunk) < need` 与 `remaining > VLEN` 等价。当 `offset >= need` 时，`chunk` 为零，两个条件均为假。

生产 RTL 的三十三位差值同时提供借位和剩余量。`REG_WIDTH == 32` 时，命令准备资格由以下表达式得到：

```systemverilog
!remaining_words[32] && remaining_words[31:0] > 32'(VLEN)
```

其他 `REG_WIDTH` 使用带有原始类型转换的完整比较，在准备周期保存结果。这样可以保留较窄寄存器参数对突发字数的截断规则。

未知输入通过位级进位函数保持分组进位网络的四态传播结果。该选择使用普通 `case` 语义。确定输入覆盖 `0` 和 `1` 两个分支，综合后的组合输出连接与仅保留确定输入表达式的模型一致。

## 运行方法

所有命令从仓库根目录执行。算术、完整控制和四态测试默认使用本目录保存的参考控制器与参考加法器；其余依赖从当前源码读取。也可以用 `--reference-root` 指定完整参考源码目录，用 `--source-root` 指定待检查源码。

```bash
python3 test/requant_load_completion/run_formal.py \
  --out build/requant_load_completion/formal

python3 test/requant_load_completion/check_four_state.py \
  --out build/requant_load_completion/four_state

python3 test/requant_load_completion/run_control.py \
  --out build/requant_load_completion/control

python3 test/requant_load_completion/check_control_four_state.py \
  --out build/requant_load_completion/control_four_state

python3 test/requant_load_completion/check_function_elimination.py \
  --out build/requant_load_completion/function_elimination

python3 test/requant_time_share/run.py \
  --out build/requant_load_completion/numeric_production \
  --vlen 16 --lanes 2 --reuse 32 --bus 64 --xilinx

python3 test/requant_load_completion/measure.py \
  --out build/requant_load_completion/measurement
```

完整控制证明包含实际配置过程、DMA 状态机、WS 参数存储内容及 IS 存储的完整驱动端口。IS 存储使用相同的任意读值，两份模型的地址、写数据、使能和存储参数均参与比较。外部输入和存储读值均未施加范围约束。

归纳证明同时检查命令有效与接收忙互斥、活动命令具有有效装载范围、忙期间接收字数与保存命令一致，以及保存资格与该命令完整末拍比较结果相等。

## 当前结果

当前 `vec_requant.sv` 的 SHA256 为
`ee49ad76b8e4571d3a146cca4885a3ea191449ff584c499d7755dc93cdc19511`。

| 检查 | 覆盖范围 | 结果 |
|---|---|---|
| 算术形式证明 | 12 组参数，64 位完整输入空间 | 通过 |
| 算术四态比较 | 32,768 组输入，393,216 次比较 | 通过 |
| 完整控制等价 | 4 组参数，16,572 位状态及输出 | 通过 |
| 控制四态比较 | 16,384 周期，98,304 次向量比较 | 通过 |
| 四态函数综合检查 | 输出连接图相同，函数对应单元数为零 | 通过 |
| 生产参数数值测试 | 75,534 周期，542,528 个 INT8/INT16 数值，608 条 DMA 命令 | 通过 |

数值测试使用 `VLEN=16`、`BUS_WIDTH=64`、`p_compute_lanes=2` 和
`MAX_IA_REUSE=32`，覆盖等待、连续参数装载、7 次配置清除和 6 次复位。
控制四态测试另外覆盖 37 次接收忙期间的复位、7 次接收忙期间的重新配置，
以及 8,899 个含未知输入的周期。

同一组依赖源码和综合选项下，完整量化模块的资源统计如下。LUT 数为布局前统计值。

| 项目 | 参考控制器 | 保存命令资格的控制器 |
|---|---:|---:|
| 逻辑 LUT | 2,830 | 2,822 |
| LUTRAM 占用 | 64 | 64 |
| SRL 占用 | 14 | 14 |
| 名义 LUT 总数 | 2,908 | 2,900 |
| FF | 1,372 | 1,373 |
| DSP | 8 | 8 |
| RAMB18 | 19 | 19 |

参考控制器的 `quant_need_load_r` 到 `state` 路径为 10 级。当前控制器在现有
命令准备边沿保存资格，`quant_need_load_r` 到 `cmd_has_more_r` 为 10 级，
`cmd_has_more_r` 到 `state` 为 3 级。完整模块的最长路径为 11 级，位于
`registered_multiplier_s32` 内部乘积归约过程；逐单元连接保存在测量目录的
`candidate/metrics.json`。

源码摘要和验证数量记录在 `validation.json`，资源与路径统计记录在
`measurement.json`。每个运行目录分别保存工具脚本、日志、输入摘要与结果摘要。
