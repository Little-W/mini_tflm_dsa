# 向量写回地址共享

`vector_engine` 按当前状态选择写回偏移，并使用公共加法表达式生成 `write_origin_next`。空间运算先将位置偏移与通道号相加，状态选择之后再加输出基址。全部运算保留 32 位地址结果。

| 写入状态 | 写回地址 |
| --- | --- |
| `EXECUTE_COMMIT` | `c.output_base + (vector_offset << 2)` |
| `ADD_STORE` | `c.output_base + vector_offset` |
| `QUANT_STREAM`、`AVG_POWER_STORE`、`AVG_WAIT`、`POOL_STORE` | `c.output_base + position_offset + channel_base` |
| `SOFT_RUN`、`VECTOR_REDUCE` | `c.output_base` |

八处地址寄存器的更新条件保持原样。接口、存储容量、输入输出周期和控制状态均保持原有行为。该实现使用普通 RTL 加法和选择表达式。

## 等价验证

```sh
python test/vector_write_address/run_formal.py \
  --out /tmp/vector_write_address/formal
```

脚本直接读取当前源码和参考提交 `67c25118`，检查除共享地址表达式外的代码保持一致，并证明全部 64 个状态值、112 位地址输入和 32 位地址输出等价。输入不附加数值范围限制，覆盖地址溢出时的低 32 位结果。

局部综合及映射后的状态验证：

```sh
python scripts/fpga/open_fpga_synth.py \
  --out /tmp/vector_write_address/local \
  --case-config /tmp/vector_write_address/formal/cases.json \
  --cases reference current \
  --wide-alu-dsp-budget 4 --wide-alu-minimum-width 8 \
  --wide-alu-maximum-chain 2

python test/vector_write_address/run_formal.py \
  --out /tmp/vector_write_address/formal \
  --mapped-case /tmp/vector_write_address/local/current
```

映射验证将真实 JSON 网表导入 Yosys，执行生产 DSP techmap，并使用 Yosys 提供的 `DSP48E1` 功能模型。两份任意且相同的 32 位地址寄存器内容作为初始状态，输入和更新使能可任意变化，证明后续寄存器状态相同。脚本同时检查映射时的源码摘要与当前表达式一致。

## 面积与组合深度

完整向量模块使用 `TILE=16`、`BUS_WIDTH=64`、`PE_COUNT=8`，两份设计均采用 53 个 DSP 的总预算、最小 8 位算术映射和最多两级组合 DSP。

```sh
python scripts/fpga/open_fpga_synth.py \
  --out /tmp/vector_write_address/vector \
  --case-config /tmp/vector_write_address/formal/vector_cases.json \
  --cases reference current \
  --wide-alu-dsp-budget 53 --wide-alu-minimum-width 8 \
  --wide-alu-maximum-chain 2
```

| 完整向量模块 | 参考提交 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 9,740 | 9,616 |
| DSP48E1 | 53 | 53 |
| 触发器 | 6,030 | 6,030 |
| RAMB36E1 | 2 | 2 |
| 分布式存储 LUT 位置 | 56 | 56 |
| CARRY4 | 391 | 383 |
| 最长寄存器之间的组合级数 | 15 | 15 |

完整向量模块减少 124 个逻辑 LUT。局部地址单元在相同映射条件下由 130 个 LUT 减少到 36 个，DSP 数量保持为 2，32 位输出寄存器保持不变，组合深度由 10 级减少到 3 级。

上述资源数量来自逻辑映射，完整 SoC 的物理 LUT 数量由后续布局报告确定。测试摘要、源码与模型 SHA-256 见 `measurement.json`。
