# 向量累加输入、舍入与状态控制

## 数据与控制结构

`vector_engine` 在现有操作数选择器中为 Hadamard 乘法选择零累加值，其余有效运算选择对应的累加数据。操作码和操作数在同一个使能边沿保存，PE 的 MAC 直接使用保存的累加输入。

`vector_pe` 与 `registered_vector_pe` 增加了默认关闭的 `p_accumulator_preselected` 参数。开启后，调用方负责在纯乘法操作中提供零累加值；乘加、求和和极值比较继续提供相应的完整 32 位累加数据。引擎使用关闭扩展乘法的 PE 配置。`registered_vector_pe` 的新参数位于已有 `p_use_dsp` 参数之后，原有位置参数顺序和端口保持一致。

舍入器分别计算各个移位级新舍弃的数据位是否非零，再并行合并这些结果。商位、保护位、输入寄存级、中间寄存级和最近偶数舍入规则保持一致。

失败标志与计算提交标志和状态一起保存。全部 91 处状态更新同时写入原有握手控制字与新增标志，保留原来的更新条件和优先级。排空条件先归并本地活动，再在末端合入共享存储的两个返回有效位。窗口有效条件保留实际使用的组合边界，输入数据仍按原来的银行选择规则写入。

## 验证结果

| 检查配置 | 任务数量 | 正确输出数量 | 案例周期总数 |
| --- | ---: | ---: | ---: |
| 8 PE，64 位总线，8 个窗口通道，共享权重与部分和存储，私有向量量化 | 616 | 170,743 | 3,422,533 |
| 16 PE，32 位总线，4 个窗口通道，私有权重与部分和存储，共享量化 | 616 | 170,743 | 3,711,728 |
| 8 PE 生产参数，固定等待性能测试 | 40 | 103,743 | 1,071,159 |

三组检查的逐案例完整统计与比较版本一致。测试使用独立整数参考，覆盖卷积、池化、向量运算、Add、Softmax、非对齐访问、部分尾拍、暂停、输出背压、错误终止和恢复。生产参数同时启用权重预取及权重写入阶段的逐拍数据与地址检查。

局部证明与四态测试包括：

- PE 全部操作编码的组合结果、任意使能和操作码序列，以及原有位置参数接口。四态检查比较 131,072 组组合结果，并检查 32,784 个接收周期和 32,752 个保持周期。
- 所有状态编码的控制字、任意状态更新序列，以及两种共享存储配置的排空条件。四态检查覆盖全部 4,096 种六位状态编码和 131,072 组排空条件。
- 舍入器八种寄存级与实现配置的完整接口等价性。FPGA 与通用配置分别运行 52,352 项四态输入检查，每项比较四种寄存配置的两个 64 位输出。

当前 RTL、测试、依赖源码、执行程序及日志的 SHA256 保存在 `validation.json`。测试默认从已保存的 Git 提交读取比较源码，也可以通过 `--reference-root` 指定独立的参考源码目录。

## 独立综合

测量使用 `TILE=16`、`PE_COUNT=8`、64 位总线、8 个窗口通道、关闭共享量化、开启共享权重及部分和存储。测量所用公共模块与 DMA 源码散列保存在验证记录中。

| 指标 | 数量 |
| --- | ---: |
| 普通逻辑 LUT | 10,593 |
| 分布式 RAM 对应的名义 LUT | 176 |
| 名义 LUT 合计 | 10,769 |
| 触发器 | 6,403 |
| DSP48E1 推断结果 | 71 |
| RAMB18E1 推断结果 | 9 |
| 完整连接图的最长寄存器间路径 | 10 级 |

RTL 使用普通数组、寄存器和算术表达式。资源数量来自 FPGA 映射；器件频率由布局布线后的时序报告确定。

## 运行方法

```bash
python test/vector_pe_accumulator/run.py \
  --source-root . --out build/vector_pe_accumulator

python test/vector_control_flags/run.py \
  --source-root . --out build/vector_control_flags

python test/vector_round_pipeline/run.py \
  --source-root . --reference aae99101 --out build/vector_round_pipeline

python test/vector_engine/run.py \
  --source-root . --out build/vector_control_production \
  --pes 8 --tile 16 --jobs 1 \
  --cache-sets 16 --cache-policy 3 --cache-line-bytes 128 \
  --bus-width 64 --window-lanes 8 --shared-storage \
  --shared-bank-bytes 8192 --shared-bank-count 7 --shared-ia-banks 2 \
  --check-weight-write-stage --rtl-assertions --stable-stimulus --xilinx
```

在生产构建命令后增加 `--skip-build --perf` 可以运行固定等待性能测试。通用参数检查使用 `--pes 16 --bus-width 32 --window-lanes 4 --shared-quant`，并启用 `--rtl-assertions --stable-stimulus`。
