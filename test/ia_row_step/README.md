# IA 配置行步长选择

幂次复用数量 1、2、4、8、16、32、64 先编码为三位移位量，再共享一个整字移位网络。复用数量 25 保留对应常数倍算术，其他输入保留单组步长。寄存器位宽小于七位时保留逐项常数匹配，以保持常数截断后的选择优先级。

行步长仍在原有配置时钟沿保存，加载、请求和连续发射的周期保持一致。

## 检查结果

`measurement.json` 记录参考提交 `eeac204b`、当前源码及工具结果。

- 从实际 RTL 提取的行步长逻辑通过十组全输入 SAT，位宽为 1、2、3、6、7、8、16、32、48、64，数据和复用数量均未限制取值。
- 完整生产 IA 加载器的 12,372 个状态和输出比较位通过形式证明。
- 同参数模块综合中，逻辑 LUT 从 1,927 降为 1,894，触发器保持 1,173 个；寄存器间最长组合路径保持 11 级，全部组合路径最长从 12 级降至 11 级。

## 复现

```sh
python3 test/ia_row_step/run_formal.py --reference eeac204b --out /tmp/ia_row_step/logic
python3 test/ia_arbiter_request/run_ia_formal.py --reference-rev eeac204b --cases soc --out /tmp/ia_row_step/state
python3 test/ia_row_step/prepare_measurement.py --reference eeac204b --out /tmp/ia_row_step/inputs
python3 scripts/fpga/open_fpga_synth.py --case-config /tmp/ia_row_step/inputs/cases.json --cases reference current --out /tmp/ia_row_step/native
```
