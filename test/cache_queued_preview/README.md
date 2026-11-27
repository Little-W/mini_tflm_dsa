# 多项请求缓存的连续预读

`p_preview_request=1` 时，缓存在正式请求前同步读取标签和数据。完整字节地址、缓存组号及查询快照匹配后，正式请求直接使用已经读取的内容；其他请求按接收顺序进入请求队列。每次正式握手保存该请求的代次、释放序号、进度和几何事件字段。

当前请求具备处理条件时，读取端同时准备下一项预读内容。读写冲突、查询有效性和元数据写入转发分别计算正式输入与预读输入的结果，再选择处理资格。哈希组号和窗口索引分别与预读快照比较，窗口模式选择匹配结果；完整地址比较与组号比较并行。

两项及以上队列的完成结果写入已有响应队列，数据、错误状态和有效信号使用同一保存边沿。队列支持同周期出队和入队，持续预读命中流每个周期接收一项请求并返回一项结果，命中结果在正式接收后的一个周期返回。

## 形式检查

```sh
python3 test/cache_queued_preview/check_parent.py --preview 1 --out build/cache_queued_preview/parent
python3 test/cache_queued_preview/check_parent.py --preview 0 --out build/cache_queued_preview/compatible
python3 test/cache_queued_preview/check_properties.py --out build/cache_queued_preview/properties
python3 test/cache_response_ready/check_return.py --out build/cache_queued_preview/return
```

完整缓存比较覆盖所有公开输出和共有寄存状态，参考为既有寄存预读版本 `0d437ded9299a7ad5ab70f30884b5344399d4d22`。参数包含请求深度 1、2、4，以及实际 SoC 的 16 组、2 路、128 字节缓存行和 64 位数据。测试分别覆盖 generic 与 FPGA 宏模式，输入不增加约束。

十四项时序性质从复位开始证明预读身份、正式接收、请求保存和响应队列关系。返回组合过程逐位比较完整数据、有效信号、错误信号及保存事件，并覆盖四态输入。

## 协议与数值检查

```sh
python3 test/cache_pipeline/run_queued_preview.py --no-direct-response --out build/cache_queued_preview/fpga --depth 2 --read-width 64 --mode fpga --cache-sets 16
python3 test/cache_pipeline/run_queued_preview.py --no-direct-response --out build/cache_queued_preview/depth4 --depth 4 --read-width 128 --mode generic --cache-sets 16
```

每组协议测试包含 26 项场景：连续预读、持续每周期接收与返回、随机反压、稳定响应保持、取消、配置切换、地址及组号不匹配、越界、填充冲突和串行模式。实际 SoC 的协议、前端数值、周期对比与完整连接测量见 [缓存响应队列的寄存分隔](../cache_response_ready/README.md)。

组号匹配与快照资格的实现说明见 [并行组号匹配](parallel_set_match.md) 和 [查询组号的并行比较](lookup_set_match.md)。
