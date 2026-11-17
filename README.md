# TFLM AI DSA

TFLM AI DSA 提供 SystemVerilog NPU、PicoRV32 SoC、TensorFlow Lite Micro 与 NMSIS-NN 驱动，以及仿真和实现工具。

本分支使用固定 INT32 部分和存储。16 个 INT32 元素组成一行，占用 64 B，通过四个 128 位端口写入共享 RAM。每个 frame 使用确定的存储区间；综合电路包含行反馈队列和 frame 控制，操作数支持 WS、IS 切换，卷积使用 DMA 内的硬件 im2col 前端。

## 硬件配置

| 参数 | 默认值 |
|---|---:|
| 脉动阵列 | 16×16 |
| AXI4 数据宽度 | 64 位 |
| AXI-Lite 数据宽度 | 32 位 |
| 共享 IA/PS 数据 RAM | 9×2 KiB，合计 18 KiB |
| 同时驻留 frame 数 | 4 |
| im2col 输入缓存 | 4 KiB |
| `PS_FORCE_RAW` | 1 |
| `CAPACITY_REPRESENTATION` | `raw32` |

参数保存在 [config/npu.mk](config/npu.mk)。`PCR_ENGINE=1` 选择共享 frame 执行路径，部分和使用 RAW32 表示。算术部分和始终保留完整 INT32 位模式。容量不足时，frame 调度器优先完成驻留输出。

## 获取源码

```sh
git clone --recurse-submodules https://github.com/Little-W/mini_tflm_dsa.git tflm_ai_dsa
cd tflm_ai_dsa
git checkout experiment/no-ps-compression
```

## 仿真

直接 INT32 存储测试需要 Verilator 和 C++ 编译器：

```sh
python3 test/ps_raw_store/run.py --out build/raw_store
python3 test/ps_raw_store/run.py --large --out build/raw_store_large
```

完整 NPU 测试需要 VCS 和 SRAM 功能模型。设置 `SRAM_ROOT` 后执行：

```sh
python3 test/ps_compression/run_sram_npu.py \
  --sram-root "$SRAM_ROOT" --force-raw --out build/raw_npu
```

测试包含 WS、IS、硬件 im2col、INT8/INT16 输入、INT32 结果检查和错误恢复。模块及 SoC 的其他入口可通过 `make help` 查看。

## Design Compiler 综合

设置标准单元和 SRAM 工艺库后，可通过 [ASIC 综合入口](asic/README.md) 构建。成对综合脚本使用相同阵列、存储参数和时钟约束：

```sh
python3 scripts/asic/run_ps_synthesis.py \
  --source-root . --force-raw --frequency 150 \
  --std-db "$PS_STD_DB" --libs "$MEM_DB_PATH" --out build/raw_synthesis
```

`MEM_DB_PATH` 包含 TT 角的 `RAMTP128X16` 和 `RAMTP1024X16` 编译库。脚本保存源文件摘要、时序报告、面积报告、SRAM 实例清单和综合网表。项目生成文件保存在 `build/`。

## 目录

| 路径 | 内容 |
|---|---|
| `rtl/` | NPU、AXI 接口和 SoC RTL |
| `drivers/` | TFLM、NMSIS-NN 和加速器驱动 |
| `test/`、`veri/` | 模块、完整 NPU 和 SoC 仿真 |
| `config/` | 硬件配置 |
| `asic/`、`fpga/` | ASIC 与 FPGA 实现入口 |
| `scripts/asic/` | 综合源文件准备和实现成本统计 |
| `docs/` | 架构、接口和实现分析 |
