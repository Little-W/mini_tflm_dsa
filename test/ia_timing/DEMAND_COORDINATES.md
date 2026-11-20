# IA 请求绝对坐标的同拍保存

`ia_loader` 在控制器保存分块请求的同一时钟边沿，保存 `p0`、`q0` 的绝对坐标。后续缓存命中判断和 DMA 描述符直接使用该寄存结果。请求接受、DMA 启动、缓存读写和阵列输出保持原有周期。

## 时序关系

控制器每个时钟边沿分别将 `request_p0`、`request_q0` 保存到 `tl_p0`、`tl_q0`。父模块的 `p0_base_q`、`q0_base_q` 在 `init_cfg` 有效时保存新配置，其余周期保持。因此，在边沿前计算下列表达式并保存，与边沿后使用相对坐标和基址计算的结果一致：

```text
demand_p0_q(t+1) = request_p0(t) + (init_cfg(t) ? cfg_p0_base(t) : p0_base_q(t))
demand_q0_q(t+1) = request_q0(t) + (init_cfg(t) ? cfg_q0_base(t) : q0_base_q(t))
```

加法显式扩展一位，保存结果低 `REG_WIDTH` 位，并使用 `unused_*_carry` 接收进位。异步复位时绝对坐标清零。配置与请求采样发生在同一边沿时，选择新配置基址；该规则同时保持未使能周期的公开坐标值。用于当前请求查询的 `request_descriptor` 继续使用当前寄存基址。

控制器接口保持原样，父模块将未消费的相对坐标输出接到 `unused_tl_p0`、`unused_tl_q0`。综合会删除这些相对坐标中没有使用者的寄存器。数据容量、队列深度和存储器实现保持原样。

## 完整状态与逐周期验证

参考提交为 `49bd78d8157d8092ac0a30f2f44f7498ed0948b4`。形式比较在参考模块内增加两个组合等价点，分别为 `tl_p0 + p0_base_q` 和 `tl_q0 + q0_base_q`，直接证明新寄存坐标与原始表达式之间的关系。比较使用简单 SAT 和时序归纳，不限制配置、请求、DMA 完成、复位等输入的取值。

| 完整加载器配置 | 已证明的状态和输出位数 |
| --- | ---: |
| SIZE16、BUS64、CACHE32、ORDERED_JOB1 | 11,129 |
| SIZE16、BUS32、CACHE4、ORDERED_JOB0 | 9,578 |
| 合计 | 20,707 |

逐周期比较覆盖全部 39 个公开输出，包括未使能时的数据与控制值。数值测试检查缓存命中、DMA 描述符、预取跨配置、尾部补齐、循环槽位和输出数据。

| 配置 | 命令或用例 | 比较周期 | 数值检查 |
| --- | ---: | ---: | ---: |
| 通用预取，CACHE4 | 251 | 57,160 | 179,920 |
| 有序预取，CACHE4 | 251 | 57,835 | 179,920 |
| 分组加载，CACHE32 | 81 | 122,287 | 724,032 |
| 合计 | 583 | 237,282 | 1,083,872 |

```sh
python3 test/ia_timing/run_formal.py \
  --out build/ia_demand_formal --reference-rev 49bd78d \
  --cases loader_ordered loader_generic
python3 test/ia_timing/run_interface.py \
  --out build/ia_demand_interface --reference-rev 49bd78d \
  --verilator verilator-modern
```

## 独立模块配置与组合路径

两个版本均采用 `SIZE=16`、`BUS_WIDTH=64`、`CACHE_BLOCKS=32`、`EXTERNAL_RAM=1`、`ORDERED_JOB=1`，并使用同一版 Yosys、公共模块和映射设置。下表的独立模块配置使用 `COUNT_WIDTH=32`，数据 RAM 由外部提供。

| 指标 | 参考提交 | 同拍保存绝对坐标 |
| --- | ---: | ---: |
| 逻辑 LUT | 5,616 | 5,646 |
| 分布式 RAM 的名义 LUT 数 | 176 | 176 |
| 触发器 | 3,080 | 3,083 |
| CARRY4 | 432 | 432 |
| DSP / BRAM | 0 / 0 | 0 / 0 |
| 模块内最长寄存器路径 | 17 | 17 |
| 寄存器到 `ext_dma_start` 的最长路径 | 14 | 10 |
| 寄存器到 `load_ia_req` 的最长路径 | 17 | 17 |
| 寄存器到 `ext_dma_p0` 的最长路径 | 10 | 1 |
| 寄存器到 `ext_dma_q0` 的最长路径 | 9 | 1 |

原来的 `p0_base_q`、`q0_base_q` 到 `ext_dma_start` 的组合连接由新的寄存边界分隔。`demand_p0_q`、`demand_q0_q` 到该启动端口的最长路径分别为 10、9 个单元。模块仍有当前请求查询路径，`load_ia_req` 的最长路径为 17 个单元。

此项修改增加 30 个逻辑 LUT 和 3 个触发器，用于缩短 DMA 启动和坐标输出路径。表中路径长度按实际连接的组合单元统计；器件时钟频率由布局布线后的延迟报告确定。

### COUNT_WIDTH=29 的独立模块配置

SoC 在 32 位地址、SIZE16 配置下使用 29 位维度计数器。保持其余参数相同，分别综合参考提交和坐标提交 `0e3c2d3`，结果如下：

| 指标 | 参考提交，COUNT29 | 同拍保存绝对坐标，COUNT29 |
| --- | ---: | ---: |
| 逻辑 LUT | 5,616 | 5,652 |
| 分布式 RAM 的名义 LUT 数 | 176 | 176 |
| 触发器 | 3,053 | 3,056 |
| CARRY4 | 432 | 432 |
| DSP / BRAM | 0 / 0 | 0 / 0 |
| 模块内最长寄存器路径 | 17 | 17 |
| 寄存器到 `ext_dma_start` 的最长路径 | 15 | 10 |
| 寄存器到 `load_ia_req` 的最长路径 | 16 | 17 |
| 寄存器到 `ext_dma_p0` / `ext_dma_q0` | 10 / 9 | 1 / 1 |

该配置增加 36 个逻辑 LUT 和 3 个触发器。`p0_base_q`、`q0_base_q` 到 DMA 启动端口的组合连接同样由坐标寄存阶段分隔；保存坐标到该端口的最长路径均为 8 个单元。

```sh
python3 test/ia_timing/run_synthesis.py \
  --out build/ia_demand_synthesis --reference-rev 49bd78d \
  --count-width 32 \
  --lock-file /path/to/synth.lock
python3 test/ia_timing/measure_demand_paths.py \
  --mapped build/ia_demand_synthesis/results/loader_reference/mapped.json \
  --pre-lut build/ia_demand_synthesis/results/loader_reference/pre_lut.il \
  --out build/ia_demand_synthesis/reference_paths.json
python3 test/ia_timing/measure_demand_paths.py \
  --mapped build/ia_demand_synthesis/results/loader_candidate/mapped.json \
  --pre-lut build/ia_demand_synthesis/results/loader_candidate/pre_lut.il \
  --out build/ia_demand_synthesis/candidate_paths.json
```

将综合命令的 `--count-width` 设为 29 可测量相同计数器配置。文中坐标提交的源码摘要为 `a299fd748d7c483b302edae6ec5c109c743128fb779042a1701a355c40dcbccb`。

源码摘要、形式结果、逐周期结果、资源统计和具体路径保存在 [IA 绝对坐标验证数据](../../docs/data/ia_demand_coordinates_validation.json)。
