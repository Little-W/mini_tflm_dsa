# NPU 与 Gemmini DW 的逐层比较

本目录的存储约束比较使用 16×16 矩阵阵列、INT8 输入、INT32 累加、AXI64、2 MiB 外部 RAM 和 80 KiB 加速器逻辑状态上限。完整模型还使用相同 PicoRV32 配置、1 KiB 指令缓存和 512 KiB TFLM arena。

外部 RAM 在每个读地址请求被接受后第 8 周期起返回首拍，连续响应每周期一拍。每个方向最多保留 4 个未完成事务，单个突发不超过 2048 B。容量统计必须采用 `generic` 展开结构，与性能仿真使用相同 RTL、参数和共享存储端口。

## 计时与性能要求

独立硬件算子采用共同输入与权重，两者零点均为零，统一使用 1/32 缩放及最近偶数舍入。计时包含冷数据传输、计算、硬件量化、写回以及 AXI 响应完成。CPU 准备布局和选择调度参数单独处理。测试台比较整个外部内存镜像，检查计算结果与输入保护。

`check_layer_speedup.py` 同时记录 Gemmini 完整命令时间与循环启动到完成时间。判断 1.2 倍要求时采用各个实测 Gemmini 候选中较短的有效区间，以整数不等式 `6 * NPU <= 5 * Gemmini` 进行比较。输出表中的小数加速比仅用于阅读。

完整模型采用两组独立固件：`perf` 记录初始化后的完整 `MicroInterpreter::Invoke()`，`trace` 记录全部节点与中间张量。RESHAPE 等软件节点参与逐层检查。两种计时分别报告，各层最低时间不用于重建整网时间。每层的两个输入分别检查，随后再计算相同输入集合的整数周期总量。

## 向量资源

`run_storage_operators.py` 与 `run_storage_models.py` 接受 `--pe-count 8` 或 `--pe-count 16`。配置记录明确列出 `vector_pe_count`、`quantization_lanes`、`window_lanes` 和 `shared_quant_enable`。检查器以容量展开中的实际 `vector_pe` 实例数量及 `vector_engine` 参数核对这些字段。

本实验的 PE16、8 bank 配置采用 16 个向量乘累加单元、16 路窗口返回，并与 GEMM 共用 16 路量化流水。`storage_vector_profile.py` 根据生产参数声明和顶层连接推导实际并行度；采用双路矩阵量化的 6 bank、7 bank 配置使用单路 DW 量化。矩阵阵列、外部总线与存储容量限制保持上述配置。报告同时列出这些资源数量、共享状态和实际存储位数。

缓存配置直接继承生产 `npu_top` 的行长、路数及集合数表达式，并检查三者乘积等于输入缓存容量。测试台和容量统计分别核对实际参数，结果保存为 `cache_line_bytes`、`cache_ways` 和 `cache_sets`。

## 输入准备

环境包提供固定工具、Gemmini DW RTL、共同算子输入以及四个模型的两个固定输入。先载入其 `env.sh`，再调用仓库脚本：

```sh
python test/gemmini_comparison/prepare_model_dw.py \
  --prepared "$NPU_EXPERIMENT_ROOT/prepared" \
  --existing-workloads "$NPU_EXPERIMENT_ROOT/workloads" \
  --out /absolute/path/model_dw_workloads
```

该步骤保留原有 36 个共同算子，并增加覆盖模型 DW 几何形状的 9 个算子，共 45 个独立硬件测试。`model_dw_coverage.json` 保存模型节点与几何形状的对应关系。几何形状测试使用共同随机张量；真实模型的零点、逐通道量化和中间输出由完整模型执行检查。

## 独立硬件执行

```sh
python test/gemmini_comparison/run_storage_operators.py \
  --repo "$PWD" \
  --reference-root "$NPU_EXPERIMENT_ROOT" \
  --workloads /absolute/path/model_dw_workloads \
  --out /absolute/path/npu_operators \
  --verilator "$VERILATOR_ROOT/bin/verilator" \
  --bank-bytes 4096 --bank-count 8 --cache-bytes 8192 \
  --pe-count 16 --jobs 2
```

`--cases` 可选择指定算子；`--prepare-only` 仅生成输入和生产调度配置。相同源码与参数的后续执行可使用 `--skip-build`。脚本核对构建文件、编译输入和仿真器 SHA-256。源码或硬件配置改变后应重新构建。

需要前端统计时，可增加 `--plusarg CONV_FRONTEND_PROFILE`；需要逐周期记录时，可增加 `--plusarg CONV_FRONTEND_TRACE`。完整执行命令写入每个结果文件。

Gemmini 使用环境包中 DW 专用版本，并在相同共同输入上分别执行 `native` 和 `im2col`。环境包的 `scripts/gemmini/run_experiments.py --stage operators` 接受共同输入目录、已构建仿真器及其生成记录。检查器要求 DW 测量实际执行专用 DW 数据流。

```sh
python test/gemmini_comparison/check_layer_speedup.py \
  --npu-results /absolute/path/npu_operators \
  --gemmini-results /absolute/path/gemmini_operators \
  --workloads /absolute/path/model_dw_workloads \
  --npu-capacity /absolute/path/npu_capacity/result.json \
  --gemmini-capacity /absolute/path/gemmini_capacity/result.json \
  --gemmini-build /absolute/path/gemmini_generated/build_manifest.json \
  --out /absolute/path/operator_targets.json
```

命令同时生成 JSON、CSV 和 Markdown。返回值为 `0` 表示配置、正确性及全部性能要求通过；存在未达到的性能项时返回 `1`，并列出周期差额。无效或不完整的输入会终止检查。

## 完整模型执行

```sh
python test/gemmini_comparison/run_storage_models.py \
  --repo "$PWD" \
  --out /absolute/path/npu_models \
  --prepared "$NPU_EXPERIMENT_ROOT/prepared" \
  --gcc "$NPU_EXPERIMENT_ROOT/tools/xpack-riscv-none-elf-gcc-14.2.0-3/bin/riscv-none-elf-gcc" \
  --verilator "$VERILATOR_ROOT/bin/verilator" \
  --picorv32 "$NPU_EXPERIMENT_ROOT/source/picorv32" \
  --shared-bank-bytes 4096 --shared-bank-count 8 \
  --im2col-cache-bytes 8192 --capacity-budget-bytes 81920 \
  --capacity-report /absolute/path/npu_capacity/result.json \
  --pe-count 16 --jobs 2 --run-jobs 2
```

该命令默认执行四个模型、两个输入的 `perf` 与 `trace`，共 16 次。固件与仿真器显式采用 4 个 IA cache blocks、16 个 PS frames 和 raw32 部分和存储。`--prepare-only` 检查工具及模型输入；`--firmware-only` 构建固件；`--build-only` 构建固件和仿真器。已经完成的有效结果可用 `--resume` 继续检查。

Gemmini 完整模型仿真器由本仓库 `model_runtime/build_sim.py` 构建，使用与 NPU 相同的行为 RAM、CPU 适配器和 SoC 模块。每种固件策略分别运行上述 16 次执行。比较 `native`、`im2col`、`pipelined` 和 `selected` 四种策略时，共运行 64 次。

```sh
python test/gemmini_comparison/model_runtime/build_sim.py \
  --out /absolute/path/gemmini_models/model_simulator \
  --gemmini-generated /absolute/path/gemmini_generated \
  --verilator "$VERILATOR_ROOT/bin/verilator" --jobs 2

python test/gemmini_comparison/model_runtime/run_suite.py \
  --out /absolute/path/gemmini_models/models_native \
  --prepared "$NPU_EXPERIMENT_ROOT/prepared" \
  --simulator /absolute/path/gemmini_models/model_simulator/obj/Vtb_model_benchmark \
  --firmware /absolute/path/gemmini_models/firmware_native_perf \
  --trace-firmware /absolute/path/gemmini_models/firmware_native_trace \
  --firmware-repo /absolute/path/firmware_sources \
  --samples 0 1 --kind both --jobs 2 --resume
```

`--firmware-repo` 指向该套固件编译时的固定源码目录，执行前后均检查文件内容。`--resume` 重新核对仿真器、固件、实际结果文件、全部中间张量及日志后保留有效结果。不同策略可在独立输出目录并行执行，单次仿真仍采用相同 RTL 周期计数。

```sh
python test/gemmini_comparison/compare_storage_models.py \
  --repo "$PWD" \
  --npu /absolute/path/npu_models \
  --prepared "$NPU_EXPERIMENT_ROOT/prepared" \
  --gemmini-sim /absolute/path/gemmini_models/model_simulator \
  --gemmini-variant "native=/absolute/path/gemmini_models/models_native=$PWD=native" \
  --gemmini-variant "im2col=/absolute/path/gemmini_models/models_im2col=$PWD=im2col" \
  --npu-capacity /absolute/path/npu_capacity/result.json \
  --gemmini-capacity /absolute/path/gemmini_capacity/result.json \
  --out /absolute/path/model_comparison

python test/gemmini_comparison/check_layer_speedup.py \
  --model-report /absolute/path/model_comparison/models.json \
  --prepared "$NPU_EXPERIMENT_ROOT/prepared" \
  --out /absolute/path/model_targets.json
```

模型核验重新读取仿真器、固件 ELF、输入 RAM 镜像、实际输出、逐层记录和容量文件。整网汇总、逐输入层记录及全部层性能要求分别保存。

## 检查器测试

```sh
python -m unittest discover \
  -s test/gemmini_comparison -p test_layer_speedup.py -v
python -m unittest discover \
  -s test/gemmini_comparison -p test_storage_vector_profile.py -v
```

测试覆盖整数边界、超出浮点精确范围的周期、不同计时起点、遗漏或重复输入、错误输出、RESHAPE、单个输入未达到要求及实际向量资源不一致。
