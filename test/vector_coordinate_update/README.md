# 向量坐标更新验证

`vector_engine_address` 对八组坐标使用完整的有符号 19 位加法，保留坐标的符号扩展、16 位无符号增量和 65536 饱和值。组合加法信号上的 `use_dsp="simd"` 属性使标准综合流程将八组运算放入四个 DSP。公开接口及寄存器更新周期保持原有行为。

## 检查内容

`run_arithmetic.py` 从指定 Git 版本和当前实际 RTL 中提取完整坐标更新代码，检查以下项目：

- 无输入约束的组合等价，包括全部 18 位坐标和全部 16 位增量。
- 160,000 次四态比较，覆盖正负边界、饱和边界、未使用的高位及 X/Z 输入。
- 标准 Xilinx 综合后的四个 DSP，以及使用完整 `xilinx/cells_sim.v` 功能模型证明的全部 272 个公开输出位。

`test/vector_dma_address/run_formal.py --direct-inputs` 直接比较完整地址模块的公开输入，在五组参数下证明无限时序等价。该选项保留独立的读取资格输入，不增加输入之间的关系假设。

完整向量测试使用具有独立模块和包定义的 Git 参考设计，对每一周期的 55 个公开输出进行比较，并检查整数参考结果和性能案例。

生产配置的 616 个功能案例共比较 3,149,621 周期，检查 170,743 个数值输出；40 个性能案例共比较 830,483 周期，检查 103,743 个数值输出。两组测试的全部公开输出及其有效周期均与参考实现一致。

## 综合配置与结果

参考提交为 `35408bcfd0ca8013a7698f718b9c7658fe9e5aa8`。完整引擎使用 `TILE=16`、`BUS_WIDTH=64`、`DMA_SIZE=64`、`PE_COUNT=8`、`WINDOW_LANES=8`、`SHARED_STORAGE_ENABLE=1`、`SHARED_STORAGE_ADDR_WIDTH=12`、`SHARED_QUANT_ENABLE=0`、`MAX_TAPS=49`、`POOL_MAX_TAPS=256`。`prepare_measurement.py` 将这些参数逐项写入实际 elaboration 的 `-G` 选项，并保存所有依赖文件的 SHA-256。

| 完整 `vector_engine` 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT 单元 | 11,404 | 11,309 |
| 分布式存储占用的名义 LUT 位置 | 176 | 176 |
| FF | 6,306 | 6,306 |
| DSP48E1 | 16 | 20 |
| RAMB18E1 | 9 | 9 |
| 内部寄存器之间的最长组合单元数 | 10 | 10 |
| 输入到内部寄存器的最长组合单元数 | 10 | 10 |
| 内部寄存器到公开输出的最长组合单元数 | 9 | 9 |

该结果来自 Pyosys/Yosys 0.71+40 的 `synth_xilinx` 映射。逻辑 LUT 数量按映射单元计数；路径统计使用实际连接、LUT 真值表依赖和 DSP 内部寄存器边界。150 MHz 频率需要由目标器件实现后的时序报告确认。

## 运行方法

需要支持 `read_slang` 的 Pyosys、Icarus Verilog 和 Verilator。Verilator C++ 编译使用单个任务。

```bash
VECTOR_CHECK_OUT="$PWD/build/vector_coordinate_update"
python test/vector_coordinate_update/run_arithmetic.py \
  --reference 35408bcf --out "$VECTOR_CHECK_OUT/arithmetic"
python test/vector_dma_address/run_formal.py \
  --reference-rev 35408bcf --direct-inputs --out "$VECTOR_CHECK_OUT/address"
python test/vector_coordinate_update/prepare_measurement.py \
  --reference 35408bcf --out "$VECTOR_CHECK_OUT/inputs"
python scripts/fpga/open_fpga_synth.py \
  --source-root "$VECTOR_CHECK_OUT/inputs/reference" \
  --case-config "$VECTOR_CHECK_OUT/inputs/cases.json" \
  --cases vector_reference --out "$VECTOR_CHECK_OUT/synthesis"
python scripts/fpga/open_fpga_synth.py \
  --source-root "$VECTOR_CHECK_OUT/inputs/current" \
  --case-config "$VECTOR_CHECK_OUT/inputs/cases.json" \
  --cases vector_current --out "$VECTOR_CHECK_OUT/synthesis"
python test/vector_engine/prepare_revision_reference.py \
  --revision 35408bcf --out "$VECTOR_CHECK_OUT/reference.sv"

vector_options=(
  --out "$VECTOR_CHECK_OUT/comparison"
  --reference-engine "$VECTOR_CHECK_OUT/reference.sv"
  --bus-width 64 --window-lanes 8 --pes 8 --tile 16
  --shared-storage --shared-bank-bytes 8192 --shared-bank-count 7
  --shared-ia-banks 1 --cache-sets 16 --cache-line-bytes 128
  --stable-stimulus --jobs 1
)
python test/vector_engine/run.py "${vector_options[@]}"
python test/vector_engine/run.py "${vector_options[@]}" --skip-build --perf
```

各脚本的 `summary.json` 保存实际结果、源文件哈希和参数；完整综合输出目录包含资源计数、真实连接的路径记录及 elaboration 命令。
