# 多项请求缓存的连续预读与同拍响应

`p_preview_request=1` 时，缓存可以在正式请求前同步读取标签和数据。两项及以上请求队列在正式接收周期比较完整的 32 位字节地址、缓存组号及前台状态；全部匹配时使用已准备内容，其他情况按接收顺序保存请求。正式请求的代次、释放序号、进度和几何事件字段仍来自该次实际握手。

当前请求能够处理时，读取端同时准备下一项预读内容。读写冲突、查询有效性和同拍元数据写入转发分别计算正式输入与预读输入的结果，再选择单比特资格。预取物理槽号按每组三项归并，替换选择的地址比较与请求处理事件并行计算。

循环预取选择并行计算全部槽位和队首后方槽位的首个匹配项，分别保留两个独热结果，再完成循环选择。每个结果保持原有的未知值传播和优先顺序。

预读命中、正式请求已经接收且当前没有在途请求时，返回端直接使用同步读取的数据。下游同时接收时，该次请求在同一周期完成；下游停顿时，数据和有效位保存到原有响应队列。队列中已有结果时，按照既有顺序返回。接收资格仅使用已经保存响应的释放事件，错误资格仅使用保存的错误响应。

## 形式检查

```bash
python test/cache_queued_preview/check_parent.py --preview 0 --out build/cache_queued_preview/compatible
python test/cache_queued_preview/check_parent.py --preview 1 --out build/cache_queued_preview/parent
python test/cache_queued_preview/check_properties.py --direct-response --out build/cache_queued_preview/properties
python test/cache_queued_preview/check_helper.py --out build/cache_queued_preview/helper
python test/cache_queued_preview/check_metadata.py --out build/cache_queued_preview/metadata
python test/cache_queued_preview/check_direct_response.py --out build/cache_queued_preview/direct_response
```

`check_parent.py` 比较完整缓存的公开输出和共有寄存状态。关闭预读时，与参数默认实现逐周期比较；开启预读时，与直接计算读地址、冲突和有效位的参考实现逐周期比较。两类比较分别覆盖 generic 和 FPGA 宏模式、请求深度 1、2、4，以及 16 组、两路、128 字节缓存行的生产参数。

`check_properties.py` 对完整缓存从复位证明十四项性质，包括保存与使用的范围结果、完整地址与组号一致、正式接收资格、请求读取地址、同拍返回顺序、同步读取数据一致性、反压保存以及响应计数。输入序列不增加约束。

辅助模块、元数据和同拍返回检查分别枚举控制信号的四态组合，并逐位或随机检查未知地址与存储数据。generic 模式显式取消 `SYNTHESIS` 和 `XILINX_FPGA`，FPGA 模式显式定义这两个宏。同拍返回检查直接提取实际请求模块中的组合过程，比较完整返回数据、有效位、错误状态和响应保存事件。

## 协议与数值检查

```bash
python test/cache_pipeline/run_queued_preview.py --direct-response --out build/cache_queued_preview/fpga --depth 2 --read-width 128 --mode fpga --cache-sets 16
python test/cache_pipeline/run_queued_preview.py --direct-response --out build/cache_queued_preview/generic --depth 2 --read-width 64 --mode generic --cache-sets 16
python test/cache_pipeline/run_queued_preview.py --direct-response --out build/cache_queued_preview/depth4 --depth 4 --read-width 128 --mode generic --cache-sets 16
python test/cache_pipeline/run_queued_preview.py --direct-response --out build/cache_queued_preview/sets256 --depth 2 --read-width 128 --mode fpga --cache-sets 256
```

每组执行 26 项检查，包括连续预读、每周期接收与返回、随机反压、稳定响应保持、取消、配置切换、地址不匹配、组号不匹配、越界、填充冲突和串行模式。稳定预读命中流的正式接收间隔和响应间隔均为一个周期，正式接收与响应在同一周期发生。

已完成 16 组完整父模块形式比较、4 组时序性质证明、8 组辅助模块形式检查、6 组元数据形式检查、8 组返回过程形式检查和 104 项协议测试。完整父模块共比较 243,848 个等价点，三个四态测试合计比较 1,752,000 次。当前缓存与前端提前描述符准备、下一行提前请求组合后，14 项空间算子的正常运行和随机反压运行均通过输出哈希与事务检查。

## 综合测量

采用完整 `conv_windowed_cache`，参数为 16 组、两路、128 字节缓存行、64 位总线、64 位返回和两项请求队列。映射设置为 6,667 ps 目标、300 ps 连线估计和最多八输入逻辑映射。

| 项目 | 连续预读、寄存返回 | 连续预读、同拍命中返回 | 同拍返回及独立优先选择结果 |
|---|---:|---:|---:|
| 逻辑 LUT | 2,983 | 3,031 | 3,040 |
| LUTRAM 名义 LUT | 68 | 68 | 68 |
| 触发器 | 2,002 | 2,002 | 2,002 |
| DSP | 18 | 18 | 18 |
| 最长寄存器间组合级数 | 10 | 10 | 10 |

完整记录及源码 SHA-256 保存在 `validation.json`。

独立优先选择结果还通过八组完整缓存的逐周期比较，共 123,046 个等价点；深度 1、2、4、8 的优先选择通过八组任意输入证明和 1,151,136 次四态比较。八槽位独立注册实例的最长组合级数由 6 降至 5。完整缓存增加 9 个逻辑 LUT，最长寄存器间组合级数保持 10。此项记录保存在 `prefetch_priority_validation.json`。

```bash
python test/cache_queued_preview/check_parent.py --reference 57b61b24 --preview 1 --out build/cache_queued_preview/priority_parent
python test/cache_lookup_parallel/check_priority.py --out build/cache_queued_preview/priority_four_state
```
