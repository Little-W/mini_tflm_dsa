# 卷积地址与通道组剩余范围

描述符的完整卷积核索引和运行通道地址采用同一个三十二位加法模块。
两个十六位部分并行计算，高段按组结合低段进位，保持模加法、四态传播和更新周期。
通道组剩余范围直接使用已保存的逐通道范围，分别准备补零输出和数据输出资格。

## 完整 DMA 测量

相同生产参数下，逻辑 LUT 从 14197 变为 14212，LUTRAM 保持 224，
DSP 从 71 变为 73，触发器保持 7688。
每拍处理 8 个窗口样本，总线为 64 位，缓存为 16 组双路、每行 128 字节，
缓存响应深度为 2。

| 路径 | 参照级数 | 当前级数 |
|---|---:|---:|
| 准备描述符到卷积核索引 | 12 | 8 |
| 组起始地址到运行地址 | 12 | 7 |
| 输入格式到运行状态 | 12 | 11 |
| 完整 DMA 最长路径 | 12 | 12 |

当前最长路径位于通道索引到请求纪元的计算。
`measurement.json` 保存完整资源、映射参数、源文件摘要和目标路径。

## 功能检查

地址加法的通用与综合形式证明及 8388 次四态比较通过。
完整几何与描述符模块的 8 种配置、完整流式模块的 5 种配置均通过证明。
42 项实际数值事务保持 178417 周期，128 条事务统计逐项一致。
详细数据位于 `results/`。

```sh
python3 test/frontend_arithmetic/check_full_address_add.py --out build/frontend_address_paths/add
python3 test/frontend_arithmetic/check_decode_match.py --reference e0610bb7 \
  --sources rtl/npu/conv/conv_im2col_geometry.sv rtl/npu/conv/conv_descriptor_commit.sv \
  --out build/frontend_address_paths/parents
python3 test/frontend_arithmetic/check_stream.py --out build/frontend_address_paths/stream
```
