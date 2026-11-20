# 读取页范围与请求格式的联合判断

`conv_axi_read_guard` 将八位 `ARLEN` 的进位分成四个两位字段。最高字段的查找表同时接收页内高位是否全为一的判断；末级查找表将进位条件与 AXI 请求格式共同计算，直接输出 `direct_legal`。数据返回、分配区间检查、页拆分及各接口周期保持原有行为。通用 RTL 保留无符号比较实现。

## 资源与路径

参考提交为 `2407d9d6`。完整模块采用32位地址、64位数据、四笔并发读取并启用 GEMM 的4 KiB页拆分。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 869 | 881 |
| FF | 392 | 392 |
| CARRY4 | 73 | 73 |
| DSP48E1 | 0 | 0 |
| 寄存器间最长组合单元数 | 10 | 10 |
| 任意地址位至 `m_arvalid` | 5 | 4 |
| 地址位10至 `m_arvalid` | 4 | 3 |
| 任意地址位至 `s_arready` | 4 | 4 |

接口边界只用于组合路径分析，生产硬件不增加寄存器。完整 SoC 的跨模块路径由对应固定提交的整机报告记录。

## 验证

官方 FPGA 原语模型与通用 RTL 各完成七组完整状态及公开输出形式比较，共比较11,000位。外部输入不增加约束。参数覆盖16、32、33、40位地址，16至256位数据，以及两种页拆分设置。

BUS32与BUS64的两种页拆分配置各比较50,000个周期，共200,000个周期。全部公开输出逐周期相同，测试包含配置更新、复位、页尾地址、长突发和随机等待。全部源码摘要、原语库摘要、参数与具体路径保存在 `measurement.json`。

## 重现

```sh
python3 test/conv_guard/run_control_formal.py --fpga \
  --reference-ref 2407d9d6 --out build/guard_page_merge/formal
python3 test/conv_guard/run_control_formal.py \
  --reference-ref 2407d9d6 --out build/guard_page_merge/generic
python3 test/conv_guard/compare.py --fpga --reference-ref 2407d9d6 \
  --verilator verilator-modern --out build/guard_page_merge/numeric
python3 test/conv_guard/prepare_page_measurement.py --reference 2407d9d6 \
  --out build/guard_page_merge/inputs
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/guard_page_merge/inputs/cases.json \
  --cases reference current --out build/guard_page_merge/synthesis
python3 test/conv_guard_page_merge/measure_paths.py \
  --source build/guard_page_merge/synthesis --out build/guard_page_merge/paths.json
```
