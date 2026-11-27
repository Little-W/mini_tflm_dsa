# 向量读取地址的末级模式选择

`vector_engine_address` 先按读取类型准备普通读取的基址和偏移。`vector_read_address_select` 在独立组合模块内选择 Softmax 查表、池化和普通读取的完整分量，再交给公共地址加法器。优先次序为 Softmax 查表、池化、普通读取。

选择过程保留三十二位基址、三十二位偏移和十六位通道分量。模块使用原有过程式 `if` 语义，控制中的未知值继续按原过程处理，被选择数据中的高阻态保持原值。该模块没有寄存器，公开请求周期和状态转换保持一致。

## 验证

- 完整地址模块在四种宏配置与两种 `p_registered_read_phase` 取值下，通过八项全部输出及寄存状态的形式等价检查。
- 直接提取生产地址选择过程，比较全部 80 位分量；八项形式等价检查和 2,097,152 次四态比较全部通过。
- 输入允许读取资格独立变化，保留任意读取类型、任意 `i_load_read_select` 位组合及未知控制。
- 已有控制字检查通过七项形式性质和 262,144 次四态比较，覆盖 89 处状态更新和九处读取类型更新。

## 完整引擎映射

测量配置为 16 通道、8 个 PE、64 位总线、共享存储和本地量化。两侧装载相同的向量引擎及其余子模块，地址模块参考提交固定为 `7c6599e002c9abb8906b73554c65a74b0fe8d780`。

| 指标 | 参考地址选择 | 独立末级选择 |
| --- | ---: | ---: |
| 逻辑 LUT | 9,794 | 9,801 |
| 计入分布式存储的布局前名义 LUT | 9,970 | 9,977 |
| 完整引擎最长寄存器路径 | 10 级 | 10 级 |
| 池化控制至地址分量 | 4 级 | 1 级 |
| Softmax 控制至地址分量 | 4 级 | 1 级 |
| 池化控制至 `rd_base_addr` | 8 级 | 6 级 |
| Softmax 控制至 `rd_base_addr` | 8 级 | 6 级 |

路径统计使用展开全部模块后的完整连接图。地址分量和 `rd_base_addr` 的分析终点只用于路径统计，资源数量来自原始映射网表。完整 SoC 统计还包含后续 DMA 仲裁选择与描述符寄存器。

## 复现

```sh
python3 test/vector_read_address_select/run.py --out build/vector_read_select
python3 test/vector_request_timing/check_address.py --reference 7c6599e002c9abb8906b73554c65a74b0fe8d780 --out build/vector_read_select_parent
python3 test/vector_read_address_phase/check_registered_sources.py --out build/vector_read_select_control
python3 test/vector_read_address_select/measure.py --out build/vector_read_select_mapping
```

`validation.json` 保存形式检查日志摘要、源码摘要、四态比较数量及完整引擎映射结果。
