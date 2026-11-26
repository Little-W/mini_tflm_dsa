# 部分和帧接收与行地址选择

`ps_frame_store` 并行检查返回流水线和解码队列是否空闲，以及当前帧的提交、回放和命令状态。已保存命令、空闲命令槽和本拍完成的命令分别形成资格，`ps_frame_ready_select` 在最后一级合并这些结果与请求、容量状态。

固定通道布局中的当前地址和初始地址各自通过 `ps_frame_address_increment` 计算下一行地址，首行读取条件只选择已经完成的计算结果。两个辅助模块使用普通组合 RTL，不增加寄存器或周期。帧存储的所有端口、内存容量、同拍操作和未知值传播保持一致。

## 验证

完整模块证明比较全部公开输出和共同状态，覆盖生产参数、紧凑参数、内部存储和轮转外部存储四种配置，并分别使用通用和 FPGA 编译方式，共 8 项证明。通用方式显式使用 `-USYNTHESIS -UXILINX_FPGA`，FPGA 方式使用 `-DSYNTHESIS=1 -DXILINX_FPGA=1`。组合检查直接提取实际帧接收、完成及预取表达式，对所有功能输入进行无约束证明，并在通用与 FPGA 编译方式下比较 184,324 次四态输入。

| 检查 | 范围 | 结果 |
|---|---|---:|
| 完整模块时序归纳 | 四种存储及行数配置，两种编译方式 | 8 项通过 |
| 实际组合控制的全部输出 | 6 个控制结果，两种编译方式 | 2 项通过 |
| 四态比较 | 随机状态、逐位未知值、请求与故障组合 | 184,324 次通过 |
| 源码布局和端口说明 | 单模块文件、普通 RTL、中文注释 | 通过 |

结果、实际输入文件摘要和测试摘要保存在 `validation.json`。

## 完整帧存储测量

使用 16 个帧槽、每帧最多 512 行、49,152 字节外部存储和固定部分和通道。两版使用相同依赖和综合参数。

| 项目 | 参考输入 | 当前 |
|---|---:|---:|
| 逻辑 LUT | 1,572 | 1,571 |
| 寄存器之间的最长组合单元数 | 11 | 10 |
| `decoded_count` 到 `frame_ready` | 7 | 3 |
| `decoder_inflight` 到 `frame_ready` | 7 | 3 |
| `frame_request` 到 `frame_ready` | 2 | 1 |
| 所有状态到 `frame_ready` 的最大值 | 7 | 6 |
| 所有状态到 `ram_read_en` 的最大值 | 8 | 7 |
| 触发器 | 1,073 | 1,073 |
| DSP48E1 | 18 | 18 |
| RAMB18E1 | 15 | 15 |

映射采用 `physical-cost`、6,667 ps 目标、300 ps 连线代价和最多 8 个输入的切割设置。所有连接路径均从真实映射结果中读取。组合级数用于检查结构，150 MHz 的实现时序由器件布局布线结果确定。完整路径保存在 `measurement.json`。

## 重复执行

在工程根目录执行：

```sh
python test/ps_frame_ready/run_control.py --reference 05c9b052 --out build/ps_frame_ready/control
python test/ps_frame_ready/run_full.py --reference 05c9b052 --mode generic --out build/ps_frame_ready/full_generic
python test/ps_frame_ready/run_full.py --reference 05c9b052 --mode fpga --out build/ps_frame_ready/full_fpga
python test/ps_prefetch_qualification/prepare.py --reference 05c9b052 --out build/ps_frame_ready/pair
python scripts/fpga/open_fpga_synth.py --case-config build/ps_frame_ready/pair/cases.json --cases reference current --out build/ps_frame_ready/pre --through pre_lut
```

分别用 `scripts/fpga/remap_fpga_luts.py` 映射两版 `pre_lut.il`。`measure.py` 接收对应的 `--mapped`、`--pre-lut` 与 `--out`，输出队列状态、请求和接受信号到真实帧接口的路径。
