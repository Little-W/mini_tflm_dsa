# 统一 block_dma / im2col 回归

本目录验证 DMA 内完成 im2col 的生产架构。WS 的 IA client 和 IS 的 kernel
client 只提交矩阵块描述符，均接收普通矩阵元素流；原图 cache 与窗口前端位于
`u_block_dma_arbiter.u_dma`。设计见 [block_dma_im2col](../../docs/block_dma_im2col.md)。

本补丁只保留源码、设计文档和测试生成器。运行不读取历史 evidence、内存镜像、
张量二进制或源码快照。默认输出均在被 Git 忽略的 `build/` 下；`--out` 可指定其他目录。

## 测试入口

| 入口 | 生成方式和验证对象 |
|---|---|
| `run.py` | SV 过程激励按坐标即时计算期望矩阵；SIZE4/16 各 14 个描述符、7 个 job |
| `run.py --legacy-only` | 原 `axi_dual_block_dma`、`axi_block_dma_arbiter` 两个独立 bench |
| `npu_cases.py` | 固定种子生成原始 NHWC/OHWI；独立标量 C 卷积和 NMSIS requant 产生完整 golden |
| `structure.py` | 读取新生成 build manifest，实际 elaboration 核对前端/cache 归属 |
| `operand_drain/run.py` | 当前 RTL 的预取尾部排空、真实 clock gate 与三个连续任务 |
| `../conv_replacement/rtl_compare.py` | 从仓库 TFLite 模型读取真实层几何，现生成完整 CNN 测试和策略对照 |
| `../conv_regression/run.py` | 当前 GEMM 数值回归；可从本地 Git 基线现导出源码并重跑逐计数对照 |

## 直接 DMA 返回合同

`tb_conv_dma.sv` 实例化生产 arbiter/DMA，按每个有效 lane 核对 slot、行、列、
valid mask、signed 数据和完成 owner。它覆盖：

- 普通 s8/s16 矩阵与 im2col 命令交替，IA/kernel 两个 owner 交替。
- padding、单 lane、归约尾零、空间尾行、group offset、stride、dilation。
- 同 job 跨 tile/client 的 cache 保留，新 job 同地址换值后的失效。
- 普通读的最后注册数据拍与下一条 im2col 启动相邻。
- AR 反压、R 等待、分配首尾、4 KiB 分段和精确输入范围。
- RRESP 错误后释放内部 owner，却不向 loader 发布成功 tile；非法描述符零外读。

地址与期望元素由过程代码计算，没有将预生成矩阵编码进源码。

## 完整 NPU 的连续序列

`npu_cases.py` 每次运行都调用 `npu.task()` 生成数值，种子固定为 1201…1206；
WS/IS 首两例使用相同种子，并逐文件验证 init/golden/required 完全相同。
描述符的六项 tiling 字段通过真实 `drivers/gempact_tiling.h` 的 C oracle 核验。
SIZE4/16 各执行以下八条命令，仅进程启动时复位一次：

1. WS 原图 3×3 卷积，空间及归约/输出含尾块。
2. 相同数值切换到 IS。
3. 插入普通 IS GEMM。
4. 同地址更换输入，接受后改变外部配置以验证 job 锁存。
5. IS 原图读取注入 RRESP 错误。
6. 错误后执行合法 IS。
7. 非法几何，要求零 AXI、零分块请求。
8. 切回 WS 验证恢复。

每个正常 Conv 的 75 个原始输入字节要求只读一次，padding 不读取。测试比较
整片内存以捕捉越界写，并统计真实 IA/kernel im2col 描述符，验证 WS/IS owner。
`case.json`、`build.json`、`summary.json` 和日志都在本次输出目录生成。

## 完整 CNN 层对照

公共生成器位于 `test/conv_models/generate_vectors.py`。它从仓库原有模型提取
MNIST、手势识别、Person Detection、MobileNetV2 的真实 HWC、Cout、kernel、
stride、dilation、四向 padding，再调用当前 C planner 的自动 R/W 选择。
输入、权重、bias 和量化参数是固定种子 `20261115` 的合成数据；这不是训练权重
整网准确率实验。标量 C 参考在每次执行时重新产生完整输出，不依赖旧 golden。

`rtl_compare.py` 对每个 policy 使用同一批新生成的内存镜像，核对完整输出和每个
输入地址的实际 AXI 读取次数。forward 模型只预测读取，周期由真实 RTL 测量。

## 运行

需要 Python 3、GCC/G++、make 和 Verilator；模型提取另需 NumPy、FlatBuffers，
安装方法见 [conv_models](../conv_models/README.md)。

```sh
make conv-dma VERILATOR=/path/to/verilator

python3 test/conv_dma/run.py --sizes 4 16 --out build/dma_matrix --verilator verilator
python3 test/conv_dma/run.py --legacy-only --out build/dma_legacy --verilator verilator
python3 test/conv_dma/npu_cases.py --sizes 4 16 --out build/dma_npu --verilator verilator
python3 test/conv_dma/structure.py --build-manifest build/dma_npu/s16/build.json \
  --out build/dma_structure --verilator verilator
python3 test/conv_dma/operand_drain/run.py --out build/dma_operand_drain --verilator verilator
python3 test/conv_replacement/rtl_compare.py --profiles 2:1024 0:1024 \
  --out build/dma_cnn_compare --verilator verilator
```

`--skip-build` 只复用可执行文件，不复用输入；runner 核对编译源哈希和 profile。
`run.py`/`npu_cases.py` 的可选 `--reuse-builds-root` 指向先前本地构建目录，
`operand_drain/run.py` 对应 `--reuse-build-root`。缺省运行自行构建，无需这些缓存。

真实 RISC-V CPU 执行软件 im2col 与硬件 im2col 的性能对照另见
[conv_soc_perf](../conv_soc_perf/README.md)，host C/RTL 接口测试不用于冒充 CPU 周期。
