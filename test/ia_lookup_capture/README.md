# IA 请求比较与启动资格

`ia_loader.sv` 在有序任务模式下，将请求标记、物理槽号及需求坐标之间的匹配结果与请求同时保存。配置接收周期使用实际更新后的坐标基址和槽号映射。DMA 启动周期直接读取保存的匹配位，并行计算请求资格与缓存标签命中结果。接口延迟和所有公开输出的更新周期保持。

`ORDERED_JOB=0` 使用完整描述符的通用比较。行数继续参与标记比较，包括未知值的传播。保存的匹配位具有异步复位，配置切换、缓存刷新和重复命中仍由原有有效状态控制。

列计数状态按参数展开：完整掩码分支直接保存 DMA 有效列，窄计数分支保存对应的列数和回绕位置。通用请求比较和非幂次尾部计算的临时字段均定义在各自分支中。

## 正确性验证

完整模块证明比较全部公共输出及共同内部状态，外部输入保持自由。捕获关系证明从实际源码提取请求、需求和槽号更新式，覆盖配置与请求在同一边沿更新的情况。四态仿真检查 X/Z 数据和控制输入。预取数值任务同时驱动两个完整模块，逐周期比较 40 个公共输出，并用独立模型检查最终数据、补零、缓存复用和请求次序。

| 检查项目 | 数量 | 结果 |
| --- | ---: | --- |
| 真实生产配置完整模块等价 | 12,706 个等价位 | 通过 |
| 通用任务完整模块等价 | 10,541 个等价位 | 通过 |
| `SIZE=3` 本地存储配置 | 6,846 个等价位 | 通过 |
| `CACHE_BLOCKS=64` 配置 | 17,571 个等价位 | 通过 |
| 实际捕获表达式的复位及归纳证明 | 6 个参数配置 | 通过 |
| 四态比较 | 1,204,386 次 | 通过 |
| 完整接口与数值比较 | 506 条命令、362,880 个数值 | 通过 |
| 完整接口逐周期比较 | 118,733 个周期 | 通过 |

两组数值任务分别使用间歇授予和持续授予，覆盖后台预取期间的缓存命中、任务配置切换、物理槽号回绕、不同 K 维尾部复用及未接收请求取消。数值模型启用 UBSan。

参数分支完整检查所用源码的摘要为 `d26ba1ab17a84266f5488cf8dc06f3472bd3a25ea301119f07c8c1a58a038f72`。四组完整状态比较分别证明 12,708、10,542、6,816、17,573 位等价；列状态与 DMA 有效数据另覆盖 11 组参数。该版本重新完成上述 40 个输出、506 条命令、362,880 个数值和 118,733 个周期的比较。

## 实际生产参数的独立综合

参数为 `SIZE=16`、`BUS_WIDTH=64`、`DMA_LANES=8`、`COUNT_WIDTH=29`、`CACHE_BLOCKS=32`、`RAM_WORD_ADDR_WIDTH=12`，启用有序任务、外部存储、DMA 请求寄存及共享写数据寄存。测量模块保留全部公开输出，并用一个相同的输出寄存器保存 `ext_dma_start`。

此表记录请求捕获结构 `af6ea435d8f26b2c941f4ff4872de8c7490e86f37f66ca693108af6ead0a7e4b` 的独立测量。参数分支版本的完整整机结果由对应源码快照单独统计。

| 项目 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 5,022 | 4,956 |
| 分布式存储 LUT | 20 | 20 |
| 布局前 LUT 合计 | 5,042 | 4,976 |
| 触发器 | 2,538 | 2,539 |
| DSP | 28 | 28 |
| RAMB36 / RAMB18 | 2 / 1 | 2 / 1 |
| 模块最长寄存器间组合级数 | 10 | 10 |
| `request_lookup_q` 到采样 DMA 启动的级数 | 8 | 7 |
| `request_lookup_q` 到 `cache_hit_done` 的级数 | 6 | 5 |
| `request_lookup_q` 到任意寄存器的最大级数 | 9 | 8 |

资源与级数来自独立模块映射。完整 SoC 中，DMA 启动之后还连接仲裁控制，整机路径需要在相同完整源码上统计。150 MHz 的实现结果由器件时序分析给出。

## 运行

在仓库根目录保存两组源码并执行证明：

```bash
python3 test/ia_lookup_capture/prepare.py --out build/ia_lookup_capture/reproduce
python3 test/ia_lookup_capture/run_formal.py \
  --source-root build/ia_lookup_capture/reproduce/candidate \
  --reference-root build/ia_lookup_capture/reproduce/reference \
  --cases production generic small wide_cache \
  --out build/ia_lookup_capture/reproduce/formal
python3 test/ia_lookup_capture/run_capture.py \
  --source-root build/ia_lookup_capture/reproduce/candidate \
  --reference-root build/ia_lookup_capture/reproduce/reference \
  --out build/ia_lookup_capture/reproduce/capture
python3 test/ia_lookup_capture/run_interface.py \
  --source-root build/ia_lookup_capture/reproduce/candidate \
  --reference-root build/ia_lookup_capture/reproduce/reference \
  --out build/ia_lookup_capture/reproduce/interface
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/ia_lookup_capture/reproduce/synthesis/cases.json \
  --cases reference current --out build/ia_lookup_capture/reproduce/synthesis/native \
python3 test/ia_lookup_capture/collect_paths.py \
  --native build/ia_lookup_capture/reproduce/synthesis/native \
  --out build/ia_lookup_capture/reproduce/synthesis/paths.json
```

`validation.json` 保存源码摘要、完整检查数量和实际映射路径。`check_columns.py` 可针对两个源码目录独立检查列状态与全部 DMA 写入数据及有效位，包含窄位宽参数分支。
