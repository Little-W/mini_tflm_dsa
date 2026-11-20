# IA 加载器配置与预取时序验证

`ia_loader` 在接收配置的同一边沿保存下一列分块的有效宽度，预取描述符生成阶段使用该寄存结果计算突发长度。二的幂分块尺寸使用有效低位保存尾部行列数，预取上下文保存前一分块列坐标。部分和帧的行数按完整分块的高位和尾部行数的低位组合，保留完整 32 位模运算结果。配置接收、DMA 请求、缓存读写和阵列输出的时钟周期保持一致。

请求绝对坐标的寄存阶段见 [IA 请求绝对坐标的同拍保存](DEMAND_COORDINATES.md)，当前请求的组合比较见 [IA 查询标记的并行加法比较](REQUEST_MATCH.md)，组索引的末组判断见 [IA 组索引的并行增量比较](LOOP_BOUNDARIES.md)，配置分块数的寄存阶段见 [IA 配置分块数提前计算](CONFIG_TILES.md)。本页下方记录帧行数优化的独立验证结果。

## 形式比较

```sh
python3 test/ia_timing/run_formal.py \
  --out build/ia_timing_formal --reference-rev b8b34d5 \
  --cases ctrl3 ctrl16 ctrl32 loader_ordered loader_generic
```

脚本从 Git 提取原始加载器与控制器，比较全部可匹配状态和输出。原始设计中增加前一分块坐标的组合等价点，描述与当前保存值相同的模运算关系。比较不限制配置、DMA 返回或复位以外的输入取值。

默认参考提交为 `aa2ef9a3`。本页记录的帧行数比较使用 `b8b34d5`，可通过 `--reference-rev` 指定参考提交。

## 数值与逐周期比较

```sh
python3 test/ia_timing/run_interface.py \
  --out build/ia_timing_interface --reference-rev b8b34d5 \
  --verilator verilator-modern
```

脚本复用 `test/ia_compact` 的预取与分组加载测试，在当前加载器中加入原始模块并共享所有输入。每个有效时钟边沿比较全部 39 个公开输出，包括没有使能时的数据与控制值。现有 C++ 测试继续检查缓存命中、DMA 描述符、尾部补齐、循环槽位和输出数值，并使用未定义行为检测器。

| 配置 | 命令或用例 | 周期数 | 数值检查数 |
| --- | ---: | ---: | ---: |
| 通用预取，CACHE4 | 251 个命令 | 57,160 | 179,920 |
| 有序预取，CACHE4 | 251 个命令 | 57,835 | 179,920 |
| 分组加载，CACHE32 | 81 个用例 | 122,287 | 724,032 |

形式比较在三个控制器参数配置及两个完整加载器配置中通过，共 27,057 个状态和输出等价位，其中有序加载器为 11,009 个，通用加载器为 9,522 个。

## 综合测量

```sh
python3 test/ia_timing/run_synthesis.py \
  --out build/ia_timing_synthesis --reference-rev b8b34d5 \
  --lock-file /path/to/synth.lock
```

可通过 `--synth-script` 指定 `open_fpga_synth.py` 的位置。测量采用 `SIZE=16`、`BUS_WIDTH=64`、`CACHE_BLOCKS=32`、`EXTERNAL_RAM=1`、`ORDERED_JOB=1`。两个版本共用缓存管理器和综合设置，数据 RAM 由外部提供。

| 指标 | `b8b34d5` | 帧行数优化版本 |
| --- | ---: | ---: |
| 逻辑 LUT | 6,087 | 5,994 |
| 触发器 | 3,080 | 3,080 |
| 进入预取描述符寄存器的最长组合路径 | 12 个单元 | 12 个单元 |
| 整个加载器的最长寄存器间组合路径 | 17 个单元 | 17 个单元 |
| DSP / BRAM | 0 / 0 | 0 / 0 |

帧行数优化版本的最长路径经过请求行坐标加法与缓存标记比较。表中的路径长度表示连通逻辑单元数量，时钟频率由器件布局布线后的延迟报告确定。每个结果目录保存源码摘要、综合日志、资源统计和具体寄存器路径。

完整记录见 [IA 帧行数验证数据](../../docs/data/ia_frame_rows_validation.json)。
