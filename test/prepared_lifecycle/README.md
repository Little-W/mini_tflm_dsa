# Prepare 配置与连续 Invoke 验证

本测试对每个模型、输入和运行时 PS 策略创建一个 TFLM interpreter，只调用一次
`AllocateTensors()`，随后使用同一输入连续调用 `Invoke()`。默认包含四个模型、
两个输入和 RAW32/adaptive 两种策略，共 16 个仿真进程；每个进程执行三次
`Invoke()`，合计 48 次完整推理。`--repeats` 支持每个 interpreter 执行 1 至 8 次。

模型为 `mnist_cnn`、`mobilenet_v1_vww`、`ds_cnn_kws` 和 `resnet8_cifar10`。
两种 PS 策略使用相同的 SoC 仿真程序和生命周期测试固件。

## 构建与运行

先验证包含训练模型、输入和 RNE 参考输出的 prepared 目录：

```bash
python3 test/model_benchmark/model_data.py --prepared /path/to/prepared
```

构建共享 IA/PS 配置的 SoC 仿真程序：

```bash
python3 test/model_benchmark/build_sim.py \
  --build-dir build/prepared_lifecycle/sim --build-only \
  --verilator /path/to/verilator --picorv32 /path/to/picorv32 --jobs 4 \
  --bus-width 64 --shared-bank-bytes 2048 --shared-bank-count 7 \
  --ps-pool-bytes 12288 --first-read-latency 8
```

执行默认的 48 次连续推理检查：

```bash
python3 test/prepared_lifecycle/run.py \
  --sim build/prepared_lifecycle/sim \
  --prepared /path/to/prepared \
  --out build/prepared_lifecycle \
  --gcc /path/to/riscv-none-elf-gcc \
  --object-cache build/prepared_lifecycle/objects \
  --jobs 4 --run-jobs 2 --repeats 3 --latency 0
```

运行脚本会核对仿真程序的源文件摘要、可执行文件摘要和构建状态。已有仿真程序
满足这些检查时，可以直接使用其目录。当前测试要求共享存储总容量为 14 KiB；
完整硬件参数保存在报告的 `settings.hardware_profile` 中。
`--models`、`--samples` 和 `--policies` 可选择其中一部分，`--jobs` 控制固件编译
并发数，`--run-jobs` 控制仿真并发数。

每个进程在 `AllocateTensors()` 前调用 `dsa_set_ps_force_raw()`。固件只构建一次，
两种策略通过运行配置选择。对象缓存以编译参数和依赖摘要验证可复用文件。

## 配置与调用记录

生命周期固件通过 GNU 链接器 `--wrap` 记录以下外部函数：

| 阶段 | 函数 |
|---|---|
| Conv 准备 | `dsa_prepare_conv_s8()` |
| Dense 准备 | `dsa_prepare_matmul_s8()` |
| Depthwise、Pool 准备 | `dsa_prepare_spatial_s8()` |
| Add 准备 | `dsa_prepare_add_s8()` |
| 矩阵与空间运算执行 | `dsa_prepared_execute()` |
| Add 执行 | `dsa_prepared_add_s8_execute()` |

记录表保存每个配置的地址、长度、类型、准备次数、执行次数和只读区间。
Conv、Dense、Depthwise 和 Pool 的配置类型为 `dsa_prepared_t`，Add 的配置类型
为 `dsa_prepared_add_s8_t`。所有被记录的配置对象都必须位于 tensor arena 中。

初始化之后采集 arena、模型和记录表；每次 Invoke 之后再采集这三个对象以及
完整输出。主机逐字节检查配置对象和描述符声明的只读区间，包括实际使用的
排列后权重、偏置和量化数组。完整模型数据始终与训练模型文件比较。

Softmax 的 inline 配置接口由独立主机测试检查 arena 指针、重复 Prepare 和执行
行为。连续推理测试统计每次推理的 Softmax 硬件任务及其完成状态。

## 每次 Invoke 的检查

- 输出的全部字节等于 prepared 目录中的 RNE 参考，固件内部的输出比较也通过。
- `dsa_total_planning_cycles()` 与初始化结束时相同，执行期间没有新增规划周期。
- `arena_used_bytes()` 与初始化结束时相同，配置指针及配置内容保持不变。
- Prepare 调用次数保持不变，每个已登记配置在本次 Invoke 中执行一次。
- 描述符中的只读区间、完整模型和外部输入保持不变。
- 硬件任务数量符合模型图，所有任务完成，AXI 错误、NPU 错误和容量重试计数均为零。

配置对象的类型、NMSIS 指针入口和 Prepare 的软件回退行为见
[TFLM 与 NMSIS](../../drivers/tflm/README.md)。主机检查命令为：

```bash
python3 test/prepared_dispatch/run.py --out build/prepared_dispatch
python3 test/nmsis_runtime/run.py --out build/nmsis_runtime
python3 test/vector_engine_driver/run_tflm_add_prepared.py --out build/tflm_add_prepared
python3 test/vector_softmax/run_tflm.py --out build/tflm_softmax_prepared
```

## 报告

`summary.json` 保存完成状态、运行配置以及每个进程和每次 Invoke 的检查结果。
每个场景目录保留 `result.json`、CPU 周期读数、硬件计数、二进制快照、配置地址
与只读范围。`firmware/firmware.json` 保存应用源文件、链接包装参数、编译器和依赖
摘要。

`invoke_cycles` 只包围 `MicroInterpreter::Invoke()`。配置调用次数的统计代码位于
这个区间内；内存快照、输出核验和下一次输入复制位于区间外。正式性能报告使用
[完整模型测试](../model_benchmark/README.md) 的普通固件。
