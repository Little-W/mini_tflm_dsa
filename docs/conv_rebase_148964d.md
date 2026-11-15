# 固定 148964d1 基线的统一 DMA / im2col 补丁

## 基线与保留功能

完整补丁固定以 `Little-W/mini_tflm_dsa` 的提交
`148964d180f52cb852c5a7e3d5c89773fa0a8ea5` 为基线。
原基于 `e8a7337` 的补丁曾与上游更新后的 Makefile 和文档索引冲突；本版已经
完成集成，并在此基础上整理为仅含源码与文档的交付。

| 上游提交 | 本补丁保留的功能 |
|---|---|
| `17481d2` | RAM 容量求解器、共享 NPU 配置、PCR 的 C 侧分块规划 |
| `148964d` | 终端 menuconfig、配置编辑和相关回归 |

根 Makefile 保留共享配置加载、默认 help、capacity 检查、menuconfig、PCR
参数下传，以及原 Conv 测试入口。`PS_FORCE_RAW`、PCR backend、容量规划和
更新后的 `vcs-pcr-soc` 行为均保留。文档索引同时包含 capacity 与硬件 Conv。

两份 `dsa_accel.c` 保留上游 PCR 检查与新增 Conv API；
`drivers/gempact_tiling.h` 沿用此基线的内容。不支持逐通道 Conv 的 PCR planner
仍在启动前拒绝请求。`veri/sim/Makefile` 的 TFLM 静态库和 SoC runtime 固件
依赖中补入 `drivers/dsa_conv.h`、`drivers/dsa_conv_impl.h`，保证头文件更新后
触发重建。

## PCR 配置与 Conv 配置

`config/npu.mk` 的上游默认值为 `PCR_ENGINE=1`。本硬件 Conv 需要标准核心，
应选择 **`PCR_ENGINE=0`**。

| 入口 | 配置来源 |
|---|---|
| 常规 SoC / ASIC 构建 | 共享配置和命令行覆盖；硬件 Conv 使用 `PCR_ENGINE=0` |
| `make menuconfig` / `capacity-*` | 保留上游容量和 PCR 配置功能 |
| `make conv-*` | runner 显式选择固定测试 profile，GEMM 回归另外覆盖 PCR |

因此 `make conv-soc-perf` 测量的是标准核心、SIZE16、IA 四块、PS 十六帧与
1 KiB 原图 cache；不是任意菜单配置的性能。PCR 拒绝与软件回退可独立执行：

```bash
make conv-pcr-guard
```

## 源码交付

本版移除此前补丁中的运行日志、ELF、固件二进制、内存镜像、数值向量、访问轨迹、
源码归档和一次性构建报告。测试不再读取这些历史文件。模型层参数从基线已有的
TFLite 文件提取，确定性数值与 golden 由生成器和 C 参考计算，GEMM 基线从本地
Git 中的 `148964d1` 导出后现场执行。

保留的设计、测试范围、生成流程和本轮复验结果见
[源码交付与即时生成测试](conv_source_only.md)。详细硬件接口和性能数据分别见
[DMA 设计说明](block_dma_im2col.md) 与 [SoC 性能报告](conv_soc_performance.md)。

## 在当前目录应用并提交

将新的 ZIP 放在仓库根目录。以下命令从固定基线建立一个新分支，适用于此前已经
提交过旧版补丁的工作区；执行前先保存未提交的修改。旧版提交仍保留在原分支。

```bash
git switch -c conv-im2col-source 148964d180f52cb852c5a7e3d5c89773fa0a8ea5

unzip -o "$(pwd)/mini_tflm_dsa_block_dma_im2col.zip" &&
sha256sum -c "$(pwd)/mini_tflm_dsa_block_dma_im2col.patch.sha256" &&
git apply --check --index --whitespace=nowarn "$(pwd)/mini_tflm_dsa_block_dma_im2col.patch" &&
git apply --index --whitespace=nowarn "$(pwd)/mini_tflm_dsa_block_dma_im2col.patch" &&
git diff --cached --stat

git commit -F "$(pwd)/mini_tflm_dsa_block_dma_im2col.commit.txt"
```

这是相对 `148964d1` 的完整补丁，不应叠加在旧完整补丁之上。`--index` 直接暂存
补丁中的文件，下载的 ZIP、patch 和 commit 说明不会因此加入提交。

`--whitespace=nowarn` 用于保留所附官方 newlib 源码和版权文本的原始空白。
补丁内容匹配与索引检查由 `--check --index` 完成。
