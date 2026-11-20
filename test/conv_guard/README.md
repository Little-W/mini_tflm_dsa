# Conv 共享读取保护器回归

字节地址生成的时序结构、当前资源和完整状态验证见 [WORD_ADDRESS.md](WORD_ADDRESS.md)。

```bash
python test/conv_guard/run.py
```

测试直接使用 `rtl/npu/conv/conv_axi_read_guard.sv`。AXI 响应器按绝对地址产生确定数据，以便覆盖 4 GiB 附近的地址，逐事务检查所有对外读取字节均属于配置的有效分配区间。地址和返回通道均有随机等待，输入、输出握手保持断言始终启用。

固定测试检查 10 条逻辑请求、46 个返回 word，包括 2 个 RRESP 错误；对外总计读取 119 字节、32 个 burst。数据由 testbench 即时生成。每次执行的命令、诊断和结果写入 `build/conv_guard/status.json`、`build/conv_guard/guard.log`，不需要归档向量或历史日志。

| 用例 | 检查内容 |
|---|---|
| 未对齐权重范围 | 前后各 3 个无效字节不能产生外部读；尾部多余 word 返回零 |
| 未对齐参数范围 | 正确收集不同 byte lane，未允许的 lane 置零 |
| 跨 4 KiB 的原 DMA 请求 | 拆分后每个外部 burst 合法，字节数不增加 |
| 完整合法请求 | 保留一个原长度的 burst |
| 部分 word 读错误 | 第一个 byte 的错误在后续 byte 正常返回后仍向上传递 |
| 完整 burst 读错误 | 错误仍对应原逻辑 beat |
| 完全在补零范围内 | 返回零，不读取外部存储器 |
| 接近 4 GiB 的尾部 | 只读高地址末尾 3 字节，不回绕访问另一低地址 allocation |
| GEMM 旁路 | 全部 AR/R 信号逐拍直接传递 |
| 混合模式 | 旁路结束后重新进入 Conv 保护模式正常工作 |

这些是读取保护器的模块验证；完整 NPU、SoC 和软件分发结果应看对应的端到端回归。

## 页内范围比较

快速通路首先检查总线字对齐和 4 KiB 页边界。页内首字索引加 `ARLEN` 得到末字索引，最高位表示请求是否跨页。分配区间的结束页号与请求页号并行比较；同一页内使用末字索引与结束地址的字索引比较。该结构保留开区间结束地址、33 位地址扩展、4 GiB 尾部和字节掩码行为。

```bash
python3 test/conv_guard/range_equivalence.py --out build/guard_page_range/equivalence
python3 test/conv_guard/compare.py --out build/guard_page_range/compare
python3 test/conv_guard/synthesis.py \
  --reference-ref aa2ef9a3 --out build/guard_page_range/synth_reference
python3 test/conv_guard/synthesis.py --out build/guard_page_range/synth_current
python3 test/dma_page_guard/run.py --guard-only --out build/guard_page_range/page_guard
```

范围证明从两版实际 RTL 提取单个分配区间的谓词，对地址、长度、传输属性和区间端点的全部输入位模式进行 SAT 检查。四个区间分别使用同一个谓词，通过逻辑或合并。检查包含 11 个参数配置，覆盖 16、32、64、128、256 位数据总线与 16、32、33、40 位地址。脚本同时检查字节选择和寄存器更新部分保持相同，完整输出由 [状态等价检查](WORD_ADDRESS.md) 覆盖。

公开输出比较使用 32/64 位总线与两种 `SPLIT_GEMM_4K` 设置，每个配置比较 50,000 个周期，包含配置变化、复位、页尾地址和长突发。独立跨页 DMA 测试完成 192 次读取、192 次写入，检查读写各 10 次错误以及四笔并发事务。

64 位数据、32 位地址、启用 GEMM 页拆分的独立 Xilinx 7 系列综合结果如下。触发器数量和所有接口周期保持不变。

| 指标 | `aa2ef9a3` | 页内范围比较 |
|---|---:|---:|
| LUT 单元 | 829 | 871 |
| 触发器 | 392 | 392 |
| CARRY4 | 81 | 72 |
| 最长组合路径单元数 | 18 | 14 |

新增 42 个 LUT 用于页号与页内位置的并行比较，完整地址相加后再比较的串联路径已消除。当前最长路径位于输出字节地址选择。完整 SoC 的 150 MHz 建立时间检查继续使用器件时序流程。
