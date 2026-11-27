# 连续像素提前读取

连续像素请求复用现有请求地址寄存器、像素寄存器和缓存响应队列。运行项等待当前数据时，可以继续发出同一分块中的后续完整像素请求；输出推进到这些像素时，直接等待已经排入队列的有序返回。

`conv_im2col_row_lookahead` 保存已发出的分块行号和下一输入、输出列坐标。`conv_im2col_request_payload` 并行计算普通请求、连续首项和后续项的数据，再选择完整地址与像素位置。`conv_im2col_request_pipeline` 统一控制请求有效位、取消、地址、索引和元数据的保存。`conv_request_index_register.o_pixel` 直接提供已有寄存器中的原始像素位置。

提前读取在 S8、输入通道数等于通道组宽度且等于读取字节数、横向步长为 1、输入基地址按读取字对齐、完整有效像素及同一输出行内启用。输入和输出空间范围分别检查；配置接收、分块提交和错误清空提前请求上下文。其他格式使用普通请求步骤。

## 检查入口

```sh
python3 test/frontend_lookahead/check_control.py --out build/frontend_lookahead/control
python3 test/frontend_lookahead/check_payload.py --out build/frontend_lookahead/payload
python3 test/frontend_lookahead/check_pipeline.py --out build/frontend_lookahead/pipeline
python3 test/frontend_lookahead/check_sequence.py --out build/frontend_lookahead/sequence
python3 test/frontend_pipeline/check_index_register.py --out build/frontend_lookahead/index
```

控制检查比较周期参考模型的全部公开状态，以及新组织中提前保存的空间坐标关系。地址检查使用 195 位自由输入，比较全部 64 位地址和像素结果，包含 2～128 字节的七种读取宽度。普通请求检查覆盖寄存和直接请求两种配置，比较完整输出和共同寄存状态。所有形式检查均不添加输入约束。

四态检查覆盖全部输入位的 `0`、`1`、`X`、`Z`。顺序检查独立计算连续请求的完整地址和像素位置，覆盖 32 位回绕、不同剩余行数、输入和输出空间边界、未知接收许可及上下文清空。数值检查使用独立 im2col 方程，覆盖 S8、S16、随机 AXI 延迟、输出背压、配置准备和描述符排队。

```sh
python3 test/frontend_pipeline/run_numeric.py --target fpga \
  --register-descriptor 1 --cache-response-depth 2 --bus-width 64 \
  --lanes 8 --cache-sets 16 --line-bytes 128 --prefetch --windowed \
  --out build/frontend_lookahead/numeric8

python3 test/frontend_pipeline/run_numeric.py --target fpga \
  --register-descriptor 1 --cache-response-depth 2 --bus-width 64 \
  --lanes 16 --cache-bytes 65536 --line-bytes 128 --prefetch --windowed \
  --out build/frontend_lookahead/numeric16
```

## 性能测试

上传性能环境的 16 PE、64 KiB 缓存配置完成两个算子的完整数值比较。普通卷积的 16 通道完整像素满足提前读取条件，执行周期为 20,935；同配置普通请求版本为 28,092。深度卷积每个描述符包含一行、八列，执行周期为 30,165。

| 算子 | 提供的 449 参考周期 | 当前执行周期 | 周期变化 |
|---|---:|---:|---:|
| `conv3x3_32_c16_o16` | 20,025 | 20,935 | +4.54% |
| `dw3x3_s1_48_c8` | 25,806 | 30,165 | +16.89% |

实际构建使用 Verilator 5.054、FPGA 条件和上传的输入与输出参考文件。请求与返回都经过寄存器，缓存需求及响应容量保持为两项。整机资源、组合级数和物理时序由完整 SoC 测量统一记录。

8 通道和 16 通道数值回归各完成 42 项任务及 1024 项配置检查，执行周期分别为 144,428 和 165,627。完整参数、源码摘要、逐项证明结果和数值报告位置保存在 [validation.json](validation.json)。

实际 DMA 测试覆盖 20 个场景，包含随机坐标与背压、普通读取与窗口读取同时进行、预留撤销、配置更新、错误排空和复位恢复。256 个单拍窗口与 128 个 S16 单拍窗口都每周期返回一项；512 个多拍响应的字间隔为 2 个周期，描述符边界最大为 4 个周期。测试显式选择描述符间隔 4，单拍要求仍为 1。

```sh
python3 test/window_dma/run.py --source-root . --fpga --jobs 1 \
  --descriptor-response-interval 4 --out build/frontend_lookahead/window_dma
```
