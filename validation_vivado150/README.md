# 共享 IA 存储与 RTL 验证结果

## 提交与存储结构

远端起点为 `caace9471dafe0236f0e2a9a40b8ddb48bdb844d`。
生产 RTL 对应 `7b3be7429fadbff512c35644ba0eaff07538673e` 及其前序提交。

`254419b640a0bdac87faf351e535dca4ed71a3fd` 独立统一 IA 数据存储接口。
该提交修改 `ia_loader`、`ia_loader_cache_mgr` 和 `npu_matrix_engine` 三份生产 RTL，
并同步共享存储测试、矩阵入口和历史版本比较入口。

IA 数据通过两个 128 位端口访问共享 SRAM。装载模块保存槽位有效信息、行列范围及读写流水状态。
完整矩阵任务使用 `SIZE=16` 和 6～9 个完整的共享存储体；不支持的存储配置通过任务完成接口返回错误，
并抑制 DMA 初始化与数据请求。独立计算、DMA 和算术模块保留各自的参数化测试。

工程默认 `IA_COMPACT_ENABLE=0`。在本次 7 个 8 KiB 存储体配置下，普通格式使用 2 个存储体保存 IA，
紧凑格式自动使用 1 个，其余容量分配给 PS。紧凑格式将原始 INT8 数值保存为一个字节，读取时恢复输入偏移。
PS 使用原始 INT32 数据；`im2col` 输入缓存容量为 4 KiB。

## 完整 SoC 的映射结果

本次使用 Yosys XC7 映射，目标器件为 `xc7a200tfbg484-3`。
配置为 16×16 矩阵阵列、8 个向量处理单元、64 位 AXI、7×8 KiB 共享 SRAM、256 KiB CPU RAM。
全部 151 个固定输入文件与生产代码逐项校验一致。

| 项目 | 当前结果 |
| --- | ---: |
| 逻辑 LUT | 56,890 |
| 分布式 RAM 标称 LUT 位置 | 656 |
| 移位寄存器标称 LUT 位置 | 14 |
| 布局前标称 LUT 合计 | 57,560 |
| FF | 41,256 |
| 自动推断的 DSP48E1 | 311 |
| RAMB36E1 | 100 |
| RAMB18E1 | 94 |
| 最长寄存器间组合单元数 | 15 |

45,000 LUT 目标尚差 12,560 个标称 LUT 位置；最长组合路径仍超过 10 级目标。
这里按映射后的逻辑、存储和移位单元统计布局前资源。实际 LUT 位置数和 150 MHz 时序需由目标器件布局布线结果确定。
当前提交尚无新的 DC 面积结果，350 万面积目标未作达成判定。

当前最长路径包括量化乘积寄存器输入，以及权重分组地址到 DMA 请求寄存器的路径。
`im2col` 的任务准备、地址基址和范围判断仍有 14 级路径。
完整端点与资源记录位于 [soc/summary.json](soc/summary.json)。
[功能资源分布](soc/area_by_function.json) 采用保留的原始网名与唯一组合扇出推断归属，
跨功能组或无法确定归属的单元单独计数，具体方法随报告保存。

## 局部路径与实现

- `conv_axi_read_guard` 使用分组的完整位宽比较。32 位总线配置为 843 LUT、356 FF，64 位配置为 1,018 LUT、392 FF；两种配置的内部寄存器间最长路径均为 10 级。
- `oa_writer` 复用相同的比较模块判断行数范围。包含模块输入的最长组合路径为 10 级，内部寄存器间最长路径为 10 级；局部映射为 1,428 LUT、944 FF、2 个自动推断的 DSP。
- `registered_multiplier_s32` 保存完整乘积，使用 4 位进位分组，量化输出延迟为 7 个使能边沿。独立量化通道最长寄存器间路径为 10 级；完整 SoC 的映射结果按上表单独统计。
- 向量运算使用统一 `vector_pe`，偏置采用注册向量加法，部分和写入分离请求接收与地址计算。
- 工程源文件列表使用当前模块定义。生产 RTL 共 141 个文件、136 个模块和 5 个 package，NPU 单文件最长 1,491 行。资源选择属性和显式 LUT、BRAM、DSP 实例检查通过。

## 功能与形式验证

| 范围 | 已完成的检查 |
| --- | --- |
| IA 共享接口 | 4 种配置逐周期等价；3,857,056 次共享 SRAM 数值比较；7,900,934 次控制比较；压缩及普通格式、取消、预取、重新配置 |
| 独立 IA 提交 | 8 个非法配置任务在 DMA 前返回错误；共享 SRAM 下 19×37×21 GEMM 正确，完整比较 131,072 个外部内存字 |
| 共享矩阵任务 | 346 项固定或随机 AXI 任务，覆盖分片、布局、INT16 反压、非法容量与恢复 |
| im2col 前端 | 126 项任务，1,599,750 个周期；配置、历史读取和四态检查 |
| 向量运算 | 8 PE 与 16 PE 配置各 616 项任务、170,743 个输出检查 |
| 最终量化实现 | 4 种配置，各 850,859 个输出；全部移位编码、暂停、清空和复位 |
| 权重缓存 | 12,895 位状态及输出等价；5 项数值配置、四态、容量和阵列集成 |
| 偏置控制和缓存 | 18 项形式配置，共 21,896 位等价；数值与四态检查 |
| SRAM 封装 | 15 项位宽、深度和端口配置，270,639 次比较 |
| AXI 读取保护 | 7 项形式配置、4 项四态配置、4 项随机比较及 10 条定向读取命令 |
| 写回 | 11 项综合形式配置、3 项仿真分支形式配置、4 项四态及 8 项数值配置 |
| 配置传播 | 125 项 Python 检查、18 项 Tcl 测试、4 项包装层展开及 4 项 32/64 位 AXI 存储事务 |

各项测试保留实际执行时使用的源码 SHA-256。最终乘法器与局部比较修改通过形式等价、完整数值及四态检查关联到系统回归。
验证记录分别位于 [IA](../test/ia_shared/external_only_validation.json)、
[矩阵](../test/matrix_layout/entry_validation.json)、
[前端](../test/frontend_pipeline/validation.json)、
[计算](vector/compute_checks.json)、[存储与算术](area/functional_checks.json)、
[配置](../test/capacity/ia_compact_validation.json)、
[读取保护](../test/conv_guard/validation.json) 和 [写回](../test/oa_writer_geometry/validation.json)。

## 真实 GEMM 的 IA 开关对比

使用 MobileNetV1 VWW、MobileNetV2 和 ResNet8 CIFAR-10 的真实激活值与训练权重，
对 12 个完整 GEMM 分别执行关闭、开启并固定任务参数、开启并自动选择任务参数，共 36 次 RTL 运行。
每次比较 INT32 累加结果、最终量化输出和完整外部内存，共检查 678,912 个累加结果。

| 模型 | 关闭时周期 | 开启时周期 | 关闭时读取字节 | 开启时读取字节 |
| --- | ---: | ---: | ---: | ---: |
| MobileNetV1 VWW | 58,746 | 58,810 | 134,656 | 134,656 |
| ResNet8 CIFAR-10 | 131,046 | 131,176 | 462,720 | 462,720 |
| MobileNetV2 | 134,754 | 134,616 | 357,248 | 354,944 |
| 合计 | 324,546 | 324,602 | 954,624 | 952,320 |

总读取量减少约 0.2414%，周期增加约 0.0173%。该接口的局部映射中，开启功能增加 708～920 LUT 与 314 FF，默认配置因此关闭紧凑格式。
开启开关仍可增加可用 IA 容量；所测自动任务参数将 IA 从 2 个存储体减为 1 个，为 PS 增加 8 KiB。
这组测试统计选定 GEMM 的周期，完整模型运行时间不在该表范围内。

输入来源、格式统计、构建参数和运行方法位于
[真实 GEMM 测试说明](../test/ia_compact_benchmark/README.md) 与
[逐项测量结果](../test/ia_compact_benchmark/results.json)。

## 重新生成映射报告

需要 Python、Pyosys、Slang 与工程已有的仿真工具。资源映射与功能归属可以用以下命令重新生成：

```bash
python3 scripts/fpga/open_fpga_synth.py --cases soc_top --out build/soc_mapping
python3 scripts/fpga/area_attribution.py \
  --mapped build/soc_mapping/soc_top/mapped.json \
  --metrics build/soc_mapping/soc_top/metrics.json \
  --out build/soc_mapping/area_by_function.json
```

功能测试入口与参数随各模块的说明、源文件及验证 JSON 保存。
