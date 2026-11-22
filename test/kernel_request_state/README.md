# 权重加载器请求资格与行接收

控制器在进入运行状态时保存待发请求资格，并在最后一次发出请求、任务完成或清除时更新这一位状态。加载器分别计算普通需求、受管理的需求和预取请求，在接收位置合并缓存命中、DMA 授予和清除条件。

待发预取状态包含管理模式资格，预取选择直接使用待发条件。返回数据按当前列对应的通道判断有效性，行结束条件独立控制累积状态。描述符、请求接收、缓存取消、返回顺序、发送重叠以及公开接口周期保持一致。

## 完整状态证明

`run_formal.py` 使用实际 RTL 展开模型，默认参考版本为 `cfcc1a95`。它检查全部公共寄存器的逐位对应关系，将对应状态作为双方共同的自由输入，并使用实际寄存器的数据输入与异步复位选择构造下一状态。所有公开输出和全部公共下一状态同时参与 SAT 比较。

新增状态 `load_pending_q` 的关系为：

```systemverilog
load_pending_q == ((state == S_RUN) && !all_loads_issued)
```

该关系先通过实际控制器的复位检查和一步无界归纳，再用于完整加载器的状态转换检查。外部输入保持自由。测试拒绝未处理的时钟类型、寄存器类型、未展开的存储或遗漏的公共状态。

| 检查项目 | 已完成结果 |
|---|---:|
| 生产配置公共寄存器状态位 | 15,216 |
| 新增资格状态位 | 1 |
| 逐位核对异步复位事件与复位值 | 2,174 |
| 无复位状态的共同自由符号位 | 13,042 |
| 控制器不变量参数配置 | 4 |

不变量参数为 `SIZE/REG_WIDTH/COUNT_WIDTH` 的 `16/32/29`、`1/8/1`、`4/16/16` 和 `16/32/33`。完整加载器证明使用生产配置 `SIZE=16`、`REG_WIDTH=32`、`COUNT_WIDTH=29`、`DATA_WIDTH=16`、`BUS_WIDTH=64`。

```sh
python test/kernel_request_state/run_formal.py \
  --out /tmp/kernel_request_formal \
  --lock-file ../soc_synth.lock
```

## 组合与四态检查

`check_control.py` 从实际加载器提取请求接收逻辑，检查全部二值输入关系，并在仿真和综合预处理模式下检查未知值与高阻值。两种模式累计完成 143,624 次四态与二值比较。

`check_rows.py` 从实际加载器提取行组装逻辑，比较全部输出位。七组 `SIZE/DATA_WIDTH/BUS_WIDTH` 参数为 `4/8/8`、`4/8/24`、`4/8/32`、`6/16/64`、`16/16/32`、`16/16/64` 和 `16/16/128`。全部二值输入 SAT 证明通过，四态比较累计 57,344 次。

```sh
python test/kernel_request_state/check_control.py \
  --source-root . --reference-root /tmp/kernel_request_formal/reference \
  --out /tmp/kernel_request_control
python test/kernel_request_state/check_rows.py \
  --source-root . --reference-root /tmp/kernel_request_formal/reference \
  --out /tmp/kernel_request_rows
```

## 实际加载事务

使用 `test/kernel_prefetch/run.py` 的独立 DMA 数据模型和实际 RTL 存储，检查 S8、S16、im2col、尾部尺寸、随机等待、缓存命中、在途命中、描述符变化、清除与排空、两个在途上下文以及加载和发送重叠。所有 C++ 编译单元启用未定义行为检查。

| BUS_WIDTH | 任务周期 | 核对权重值 | 逻辑加载与发送块数 | DMA 传输次数 |
|---:|---:|---:|---:|---:|
| 32 | 45,050 | 72,960 | 285 | 319 |
| 64 | 29,443 | 72,960 | 285 | 312 |
| 128 | 21,204 | 72,960 | 285 | 310 |
| 合计 | 95,697 | 218,880 | 855 | 941 |

各次 DMA 传输均完成，公开请求和完成周期保持一致。生产配置的任务周期为 29,443。

```sh
python test/kernel_prefetch/run.py \
  --source-root . --bus-width 64 --count-width 29 --fpga \
  --out /tmp/kernel_request_numeric_64
```

将 `--bus-width` 分别设为 `32` 和 `128` 可运行另外两组已记录的检查。

## 资源与路径

独立综合保留完整加载器、控制器、行存储及全部公开接口，使用行为级算术与存储推断。

| 项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| 名义 LUT | 3,407 | 3,436 |
| FF | 2,333 | 2,334 |
| DSP48E1 | 24 | 24 |
| RAMB36E1 | 64 | 64 |
| 完整寄存器路径图最大组合级数 | 12 | 10 |

```sh
python scripts/fpga/open_fpga_synth.py \
  --source-root . --case-config test/kernel_request_state/synthesis_cases.json \
  --cases current --out /tmp/kernel_request_measure \
  --wide-alu-dsp-budget 740 --rtl-dsp-attributes \
  --lock-file ../soc_synth.lock
```

`validation.json` 保存实际参数、检查数量、源码散列和原始报告的路径与散列。整机路径由对应 SoC 固定源码版本的完整测量确定。
