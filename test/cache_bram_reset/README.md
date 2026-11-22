# 窗口缓存的存储与状态验证

`conv_read_cache` 提供公共缓存接口，`conv_windowed_cache` 实现窗口访问，`conv_read_cache_reference` 实现参考策略，`conv_cache_rank_table` 保存替换来源。四个模块分别保存在同名文件中。

生产缓存有 16 组、每组 2 路，每行 128 字节，总数据容量为 4 KiB。AXI 返回宽度为 64 位，ASIC 生产读取宽度为 128 位，需求队列有 2 项，预取队列有 8 项。

## 存储组织

标签、代次和替换顺序使用公共 `regfile`。同步读取端口保持同一采样边沿；单项需求队列的直接标签比较保留异步读取。元数据的有效位单独管理，数据阵列通过普通 RTL 推断存储。

ASIC 配置的预取地址与代次共用一个 8 项、每项 64 位的数组，总计 512 位。8 个固定读取端口与一个活动选择端口读取同一份内容。预取入队、槽位交换、活动选择及队列有效位采用相同的更新事件。队列容量、每周期读取能力和公开握手周期保持一致。

14 个有效使用的数据字段采用仅由时钟触发的保存过程，复位与配置接收期间禁止写入。有效位和控制状态使用异步复位。原有写入条件及四态 `if` 语义参与比较。

## 仿真断言

`NPU_SIM_ASSERT` 根据真实写入事件记录有效位、标签、来源、代次和替换顺序，再逐周期检查有效缓存行的未知值。三个来源存储体分别记录写入，按异或关系得到来源编码。记录过程保留写使能、写掩码和未知地址的四态行为。

断言也检查有效标签读取及替换信息消费点的真实输出。断言使用公开读写接口，适用于公共存储的寄存器实现和 ASIC SRAM 实现。

## 完整模块与当前子模块检查

存储共享的完整模块比较覆盖公开输出与内部状态，外部输入保持自由。生产配置使用 `READ_WIDTH=128`，同时检查所有固定预取槽位及活动选择结果。

| 完整缓存配置 | 等价位 |
| --- | ---: |
| 8 组、2 路、行长 16 字节、BUS32、READ32、需求深度 1 | 9,327 |
| 8 组、1 路、行长 16 字节、BUS64、READ32、需求深度 4 | 4,681 |
| 16 组、2 路、行长 128 字节、BUS64、READ128、需求深度 2 | 43,584 |
| 合计 | 57,592 |

ASIC SRAM 数值比较完成 13 个场景，接收 250 个请求，完成 248 个请求，复位取消 2 个请求。预取队列峰值为 8 项，完成 11 次槽位交换和 2 次同时入出队。连续命中的请求接收间隔与结果返回间隔均为 1 个周期。

当前独立 `conv_windowed_cache.sv` 的专用检查结果如下：

| 检查 | 范围 | 结果 |
| --- | --- | --- |
| 预取共享存储 | 576 个输出位，8 个固定端口和一个活动端口 | 完整等价 |
| 预取存储四态比较 | 8,192 个周期、16,384 次比较，其中 11,376 次含未知输出 | 通过 |
| 元数据记录与实际存储 | SETS 2、16、128，共 5,980,160 次四态比较 | 通过 |
| 14 个数据字段的时钟更新 | 300,000 次四态比较 | 通过 |
| 查询快照有效位 | 4 种计数位宽、200,000 次四态比较 | 通过 |
| 活动预取快照 | 5 种地址参数组合、300,000 次四态比较 | 通过 |
| 同步标签匹配 | 6 组形式参数、20,000 次四态比较 | 通过 |
| 地址范围与填充边界 | 12 组全部输入 SAT | 通过 |

完整存储共享的源码摘要与当前子模块摘要分别记录在 [prefetch_shared_validation.json](prefetch_shared_validation.json)，元数据断言结果记录在 [metadata_observer_validation.json](metadata_observer_validation.json)。公共算术及模块体对应关系由 [公共模块验证](../resource_neutral_arithmetic/README.md) 检查。

## 运行

参考目录应包含对应版本的 `rtl` 文件及公共模块。数值比较分别读取两份源码的完整依赖，独立命名参考模块，随后逐周期比较公开输出、预取状态及数值。

```bash
python3 test/cache_bram_reset/check_metadata_observer.py \
  --out build/cache_metadata_observer

python3 test/cache_bram_reset/check_prefetch_keys.py \
  --source-root . --reference-root build/cache_prefetch_shared/reference \
  --out build/cache_prefetch_storage

python3 test/cache_storage/compare.py \
  --source-root . --reference-root build/cache_prefetch_shared/reference \
  --asic --extra-source asic/rtl/smic40_sram_1r1w.sv \
  --extra-source test/asic_regfile/sram_model.sv \
  --cache-sets 16 --line-bytes 128 --read-width 128 --defer-retire-shift \
  --bus-widths 64 --profiles 2x2 --compare-prefetch-keys --jobs 1 \
  --out build/cache_prefetch_numeric
```

`compare.py --lint-only` 检查相同参数、参考依赖和数值比较模型的语法与接口。完整模块形式比较由 `run_formal.py` 执行，`--asic --observe-prefetch-keys` 同时观察共享存储的全部槽位与活动读取结果。

`area_breakdown.py` 按映射单元的后继寄存器和公开输出整理面积，同一逻辑单元只计算一次。资源和组合深度应使用完整设计在相同源码和配置下的综合结果。
