# IA 查询标记的并行加法比较

有序任务的查询标记包含绝对行坐标高位、绝对列坐标高位和有效行数。`ia_loader` 使用两个 `add_equal` 实例检查坐标加法等式，将各位进位的一致性并行合并为查询比较结果。模块接口、保存状态和请求周期保持一致。

## 坐标与标记比较

每个绝对坐标由当前相对坐标和配置基址相加得到。比较高位标记时，低 `LOG2_SIZE` 位加法产生的进位接入 `add_equal.i_carry_in`。这样可完整保留 32 位模运算和高位截取的语义，不需要约束相对坐标或配置基址的低位。

`ORDERED_JOB=0` 使用包含地址、坐标和数据格式字段的完整标记比较。有序任务和通用任务的命中判断均复用两个已保存标记的相等关系：查询就绪条件已经确认 `request_lookup_q` 等于当前描述符标记，因此命中判断比较 `request_tag_q == request_lookup_q`。需求返回路径具备相同的查询标记条件，也复用该比较。预取命中使用对应的已保存预取标记比较。

两个 `add_equal` 实例使用显式边界信号，全部为当前周期的组合逻辑。相关 RTL 使用中文注释，不新增函数或存储器属性。

## 形式与逐周期验证

参考提交为 `d2c4b8fda5ac796692791792972712582d246b4d`。形式比较共享所有输入，覆盖以下完整加载器配置：

| 配置 | 状态和输出等价位数 |
| --- | ---: |
| SIZE16、BUS64、CACHE32、外置 RAM、有序任务 | 11,193 |
| SIZE16、BUS32、CACHE4、外置 RAM、通用任务 | 9,642 |
| SIZE3、BUS32、CACHE4、本地 RAM、有序任务 | 6,349 |
| 合计 | 27,184 |

全部比较通过。非二的幂尺寸采用本地 RAM 配置，验证坐标高位截取时的进位处理。`add_equal` 自身的九种位宽全部输入证明见 [加法等式检查验证](../add_equal/README.md)。

逐周期测试比较全部 39 个公开输出，包含未使能周期的值，并继续检查数据、缓存命中、预取跨配置、循环槽位和 DMA 请求。通用预取、有序预取、CACHE32 分组加载三组测试全部通过，共 583 个命令或用例、237,282 个周期和 1,083,872 次数值检查。

```sh
python3 test/ia_timing/run_formal.py \
  --out build/ia_request_formal --reference-rev d2c4b8f \
  --cases loader_ordered loader_generic loader_local3
python3 test/ia_timing/run_interface.py \
  --out build/ia_request_interface --reference-rev d2c4b8f \
  --verilator verilator-modern
```

## 独立模块配置与测量

两个版本均采用 SIZE16、BUS64、CACHE32、外置 RAM、有序任务，同一版 Yosys 和公共模块。下表的独立模块配置使用 `COUNT_WIDTH=32`。

| 指标 | 参考提交 | 并行比较与标记共享 |
| --- | ---: | ---: |
| 逻辑 LUT | 5,646 | 5,750 |
| 分布式 RAM 的名义 LUT 数 | 176 | 176 |
| 触发器 | 3,083 | 3,083 |
| CARRY4 | 432 | 434 |
| DSP / BRAM | 0 / 0 | 0 / 0 |
| 模块内最长寄存器路径 | 17 | 17 |
| 寄存器到 `load_ia_req` 的最长路径 | 17 | 13 |
| 寄存器到 `ext_dma_start` 的最长路径 | 10 | 9 |
| `p0_base_q` 到 `load_ia_req` 的最长路径 | 17 | 11 |
| `q0_base_q` 到 `load_ia_req` 的最长路径 | 15 | 9 |
| 寄存器到 `ext_dma_p0` / `ext_dma_q0` | 1 / 1 | 1 / 1 |

32 位计数器配置增加 104 个逻辑 LUT 和 2 个 CARRY4，缩短当前请求的查询比较路径。该配置的模块最长路径从 `u_ctrl.l2_idx` 经过递增和比较进入 `u_ctrl.pf_r_target`。路径长度表示实际连接的组合单元数量，器件时钟频率由布局布线后的报告确定。

### COUNT_WIDTH=29 的独立模块配置

SoC 在 32 位地址、SIZE16 配置下使用 29 位维度计数器。其余参数保持一致时，查询比较的资源与路径如下：

| 指标 | 参考提交，COUNT29 | 并行比较与标记共享，COUNT29 |
| --- | ---: | ---: |
| 逻辑 LUT | 5,652 | 5,616 |
| 分布式 RAM 的名义 LUT 数 | 176 | 176 |
| 触发器 | 3,056 | 3,056 |
| CARRY4 | 432 | 434 |
| DSP / BRAM | 0 / 0 | 0 / 0 |
| 模块内最长寄存器路径 | 17 | 15 |
| 寄存器到 `load_ia_req` 的最长路径 | 17 | 13 |
| 寄存器到 `ext_dma_start` 的最长路径 | 10 | 11 |
| `p0_base_q` 到 `load_ia_req` 的最长路径 | 17 | 11 |
| `q0_base_q` 到 `load_ia_req` 的最长路径 | 15 | 9 |
| 寄存器到 `ext_dma_p0` / `ext_dma_q0` | 1 / 1 | 1 / 1 |

29 位计数器配置减少 36 个逻辑 LUT，触发器数保持一致。当前最长路径从 `global_reduction_q` 进入 `u_ctrl.l2_group_row_step_b`，长度为 15 个单元；`u_ctrl.w_group_idx` 到 `u_ctrl.w_cur_r` 的路径同样为 15 个单元。

从 `49bd78d` 到查询比较提交 `7c8fb19` 的完整模块形式比较，在 `COUNT_WIDTH=29` 时通过 11,096 个状态和输出等价位，覆盖坐标同拍保存和并行查询比较两项修改。两项合计的 29 位配置保持 5,616 个逻辑 LUT，触发器从 3,053 增至 3,056，模块最长路径从 17 个单元降至 15 个单元。

```sh
python3 test/ia_timing/run_formal.py \
  --out build/ia_count29_formal --reference-rev 49bd78d \
  --cases loader_ordered29
```

```sh
python3 test/ia_timing/run_synthesis.py \
  --out build/ia_request_synthesis --reference-rev d2c4b8f \
  --count-width 32 \
  --lock-file /path/to/synth.lock
python3 test/ia_timing/measure_demand_paths.py \
  --mapped build/ia_request_synthesis/results/loader_candidate/mapped.json \
  --pre-lut build/ia_request_synthesis/results/loader_candidate/pre_lut.il \
  --out build/ia_request_synthesis/candidate_paths.json
```

将综合命令的 `--count-width` 设为 29 可测量相同计数器配置。文中查询比较提交的源码摘要为 `8324e3d3e53289d733d1f3ac318e1cbd1d4ea4d8a8b9ceabacab8efdaa6bc798`。

完整源码摘要、验证数据和路径保存在 [IA 查询比较验证数据](../../docs/data/ia_request_match_validation.json)。
