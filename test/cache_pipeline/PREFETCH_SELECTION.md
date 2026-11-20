# 预取队列的循环优先选择

`conv_windowed_cache` 的预取队列包含八个逻辑位置。每个位置保存物理槽位索引，物理槽位中的描述包含地址、代次和替换信息。选择过程从 `pf_head` 开始循环查找当前代次的有效描述；全部位置均不匹配时，选择 `pf_head`。

## 组合结构

每个固定逻辑位置根据有效位和物理槽位的代次匹配位，产生一个 `pf_current_by_slot` 位。每个候选位置并行检查循环次序中更早的匹配项，形成 `pf_pick_by_slot`。逻辑索引 `pf_pick_comb` 和物理索引 `pf_read_slot` 分别由同一个选中向量归约得到。

循环优先级由队首与两个固定位置之间的大小关系表示。最大位置的边界关系在生成阶段化为常量。整个选择结构使用显式组合赋值和命名生成作用域。

队列状态及其更新时钟边界保持一致，包括队首、队尾、计数、有效位、位置交换和描述寄存器。选择逻辑没有增加状态或响应周期。缓存仍可每周期接收和返回一个命中字；预取队列仍可同时接收新描述并移除已完成描述。

## 面积与组合路径

综合参数为 128 组、双路、每行 16 字节、64 位 AXI 数据总线、请求深度四。比较源文件来自提交 `35c3623`；主分支提交 `c64772b` 中的四个综合源文件与其完全一致。

| 项目 | 比较版本 | 当前版本 |
|---|---:|---:|
| 逻辑 LUT | 5,447 | 5,252 |
| LUT RAM 占用的名义 LUT 数 | 340 | 340 |
| 打包前两者合计 | 5,787 | 5,592 |
| 触发器 | 2,424 | 2,424 |
| RAMB18E1 | 24 | 24 |
| CARRY4 | 118 | 117 |
| 模块最长组合单元数 | 14 | 14 |
| 到 `pf_pick` 数据输入的最长组合单元数 | 12 | 11 |
| 到 `pf_addr`、`pf_epoch` 数据输入的最长组合单元数 | 13 | 13 |
| 到 `pf_index`、`pf_retire`、`pf_index_valid` 数据输入的最长组合单元数 | 12 | 12 |

逻辑 LUT 减少 195 个，约为比较版本的 3.58%。表中组合路径按映射网表的实际连接逐位统计，包括 LUT、进位及存储读出单元。物理 LUT 数和 150 MHz 时序要求由完整 SoC 的布局布线结果评估。

## 验证范围

形式验证从两个实际 RTL 文件提取选择逻辑，对全部 43 个输入位进行无约束 SAT 等价证明。这些输入覆盖队首、八个有效位、八个代次匹配位和八个物理槽位映射。比较两个三位索引输出，不要求位置映射满足排列关系。脚本还检查选择结构及其声明以外的模块正文完全一致。

逐周期比较包含 32 位和 64 位 AXI 总线，每种总线分别运行双路深度四、单路深度四及双路深度一，共六组配置。每组覆盖十三项功能，包括连续命中、响应暂停、范围错误、AXI 错误恢复、配置等待、执行期间复位、队列满载、跨代次选择、非队首移除和同时接收与移除。比较握手、状态以及有效周期内的响应数据和 AXI 地址字段，同时检查队列索引、计数和已选择描述。

生产缓存容量的前端回归运行九个卷积任务，共 325,800 个周期，启用预取并检查数值结果、AXI 事务和缓存统计。

## 复跑方法

以下命令使用可用的 Pyosys、Slang 插件和 Verilator。面积比较的两个目录均应包含对应的 `mapped.json` 和 `pre_lut.il`。

```sh
python3 test/cache_pipeline/run_prefetch_select_equivalence.py \
  --reference-ref c64772b --out build/cache_prefetch_select/formal

python3 test/cache_storage/compare.py \
  --reference-commit c64772b --verilator verilator-modern \
  --out build/cache_prefetch_select/compare

python3 test/windowed_cache/run.py --cache-sets 128 --cache-policy 3

python3 test/cache_storage/synthesis.py \
  --out build/cache_prefetch_select/current_synthesis

python3 test/cache_pipeline/measure_prefetch_select.py \
  --reference build/cache_prefetch_select/reference_synthesis \
  --current build/cache_prefetch_select/current_synthesis \
  --out build/cache_prefetch_select/paths.json
```

比较版本的独立综合使用 `test/cache_storage/synthesis.py --reference <目录>`。该目录应包含提交 `c64772b` 中的 `conv_read_cache.sv`、`conv_sdp_ram.sv`、`conv_axi_span_reader.sv` 和 `REGFILE.v`。综合脚本对输入文件生成快照，验证过程中同时检查源文件散列。

资源、组合路径、形式证明及功能测试摘要保存在 `docs/data/cache_prefetch_selection_validation.json`。
