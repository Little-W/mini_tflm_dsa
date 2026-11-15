# Conv 共享读取保护器回归

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
