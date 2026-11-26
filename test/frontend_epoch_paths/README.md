# 通道请求索引与流式资格

通道请求索引共享配置偏移和当前通道的分段和值，再根据传输步长选择完整十八位结果。
高位部分使用普通加法推断算术资源，低位进位按短分组并行计算。
选择表达式保持多位选择、全零选择和未知值输入的原有语义。

流式范围分别计算八位数据、十六位数据与补零输出的资格，输入格式参与最终选择。
错误更新先合并当前操作的结果，再处理配置接收和描述符提交的优先关系。
全部模块使用原有寄存周期。

## 完整 DMA 资源与路径

参照提交为 `9c3f2718`。两份完整 `axi_dual_block_dma` 使用相同依赖、映射参数和生产配置：
SIZE=16、64 位总线、8 个窗口通道、16 组双路缓存、128 字节缓存行、缓存响应深度 2。

| 指标 | 参照 | 当前 |
|---|---:|---:|
| 逻辑 LUT | 14212 | 14184 |
| 存储 LUT | 224 | 224 |
| 名义 LUT 总数 | 14436 | 14408 |
| DSP | 73 | 74 |
| 触发器 | 7688 | 7688 |
| 完整 DMA 最长组合级数 | 12 | 12 |
| 当前通道到请求索引 | 12 | 10 |
| 历史范围到错误寄存器 | 10 | 8 |
| 行回绕结果到缓存字命中 | 11 | 10 |
| 行起始地址到状态寄存器 | 11 | 10 |
| 通道组范围到输出坐标 | 11 | 10 |

当前最长路径为末列资格到状态寄存器的十二级组合逻辑。
输入格式到状态寄存器仍为十一级。
`measurement.json` 保存源文件摘要、映射参数、完整资源、目标路径和映射等价结果。
这些数据对应完整 DMA，完整 SoC 的资源与路径在集成测量中另行检查。

## 功能检查

29 项任意输入形式证明、5 项完整流式模块的时序归纳和 518832 次四态比较全部通过。
通用编译显式取消 SYNTHESIS 与 XILINX_FPGA，综合编译显式启用相应定义。
42 项实际数值事务保持 178417 周期，128 条统计记录逐行一致。
`results/` 保存每项证明、输入条件、源文件摘要及事务统计。

```sh
python3 test/frontend_arithmetic/check_epoch_sum.py --out build/frontend_epoch_paths/epoch
python3 test/frontend_arithmetic/check_format_range.py --out build/frontend_epoch_paths/format
python3 test/frontend_arithmetic/check_error_update.py \
  --source rtl/npu/conv/conv_im2col_error_update.sv \
  --helper rtl/npu/conv/conv_im2col_error_select.sv \
  --reference 9c3f2718 --out build/frontend_epoch_paths/error
python3 test/frontend_arithmetic/check_decode_match.py --reference 9c3f2718 \
  --sources rtl/npu/conv/conv_im2col_geometry.sv --lanes 2 8 \
  --out build/frontend_epoch_paths/geometry
python3 test/frontend_arithmetic/check_stream.py --out build/frontend_epoch_paths/stream
```
