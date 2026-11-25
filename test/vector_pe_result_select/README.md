# 向量 PE 输出来源寄存验证

`vector_pe` 在接收操作数的同一使能边沿保存乘加、零值和极值输出资格。关闭扩展乘法时，每位输出由乘加结果、累加值、符号扩展输入及三个选择信号组成。全部数据和资格共同暂停，输出周期与操作数接收关系保持一致。

扩展乘法、累加预选参数、默认操作码及 X/Z 操作码均保留原有输出行为。

## 形式与四态检查

```bash
python test/vector_pe_result_select/run.py \
  --reference f821b566 \
  --out /tmp/vector_pe_result_select/validation
```

形式检查覆盖 `ENABLE_EXTENDED_MULTIPLY` 与 `p_accumulator_preselected` 的四种组合。组合算术证明检查全部 32 位输出；时序归纳检查完整的 70 位操作数、操作码及输出资格寄存关系。首次接收后的使能、操作码和数据均不受约束。

四态测试包含初始未知状态、全部操作码、逐位 X/Z 注入以及使能为 0、X、Z 时的保持行为。默认测试完成 282,628 次采样、1,130,512 项输出比较和 24,588 项保持检查。

## 映射后的器件功能模型

```bash
python test/vector_pe_result_select/prepare_measurement.py \
  --reference f821b566 \
  --out /tmp/vector_pe_result_select/inputs

for version in reference candidate; do
  python scripts/fpga/open_fpga_synth.py \
    --source-root /tmp/vector_pe_result_select/inputs/$version \
    --case-config /tmp/vector_pe_result_select/inputs/cases.json \
    --cases $version \
    --out /tmp/vector_pe_result_select/synthesis
done
```

`run_mapping.py` 读取候选映射目录中的网表，并检查其输入源码 SHA-256 与当前 PE 一致。`--cells-sim` 指定 Yosys 安装中的 `share/xilinx/cells_sim.v`；该文件提供完整的 DSP48E1 算术模型。Verilator 数值比较覆盖 4,096 周期、32,768 项八通道输出及 4,680 项暂停周期输出。

```bash
python test/vector_pe_result_select/run_mapping.py \
  --mapped /tmp/vector_pe_result_select/synthesis/candidate \
  --cells-sim /path/to/yosys/share/xilinx/cells_sim.v \
  --out /tmp/vector_pe_result_select/mapped_comparison
```

八个 PE 的全部端口保持活跃，测量结果如下。

| 项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 659 | 409 |
| FF | 515 | 516 |
| DSP48E1 | 8 | 8 |
| 输入至寄存器最长组合级数 | 1 | 1 |
| 寄存器至输出最长组合级数 | 5 | 5 |

## 完整向量引擎

完整引擎使用 `TILE=16`、`BUS_WIDTH=64`、`DMA_SIZE=64`、`PE_COUNT=8`、`WINDOW_LANES=8`、`SHARED_STORAGE_ENABLE=1`、`SHARED_STORAGE_ADDR_WIDTH=12`、`SHARED_QUANT_ENABLE=0`、`MAX_TAPS=49`、`POOL_MAX_TAPS=256`。综合选项通过实际 `-G` 参数传入。

```bash
python test/vector_coordinate_update/prepare_measurement.py \
  --reference f821b566 \
  --out /tmp/vector_pe_result_select/vector_inputs

for version in reference current; do
  python scripts/fpga/open_fpga_synth.py \
    --source-root /tmp/vector_pe_result_select/vector_inputs/$version \
    --case-config /tmp/vector_pe_result_select/vector_inputs/cases.json \
    --cases vector_$version \
    --out /tmp/vector_pe_result_select/vector_synthesis \
    --max-register-path-cells 10 --require-register-path-limit
done

python test/vector_engine/prepare_revision_reference.py \
  --revision f821b566 \
  --out /tmp/vector_pe_result_select/vector_reference.sv

python test/vector_engine/run.py \
  --out /tmp/vector_pe_result_select/vector_comparison \
  --reference-engine /tmp/vector_pe_result_select/vector_reference.sv \
  --bus-width 64 --window-lanes 8 --pes 8 --tile 16 \
  --shared-storage --shared-bank-bytes 8192 --shared-bank-count 7 \
  --shared-ia-banks 1 --cache-sets 16 --cache-line-bytes 128 \
  --stable-stimulus --jobs 1
```

参考聚合文件包含 25 份源文件和 28 个独立重命名的模块及包定义。完整功能比较通过 616 个案例、170,743 个数值输出，并在 3,149,621 个周期逐项比较 55 个公开输出。相同命令添加 `--skip-build --perf` 后，通过 40 个性能案例、103,743 个数值输出和 830,483 个周期的公开输出比较。

完整向量引擎的测量保持 33 份依赖文件及全部公开端口，其中仅 `vector_pe.sv` 改变。路径分析包含 TWO24 独立通道模型。

| 项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 11,309 | 10,975 |
| 分布式存储 LUT | 176 | 176 |
| 装箱前名义 LUT 总数 | 11,485 | 11,151 |
| FF | 6,306 | 6,307 |
| DSP48E1 | 20 | 20 |
| RAMB18E1 | 9 | 9 |
| 寄存器之间最长组合级数 | 10 | 10 |
| 输入至寄存器最长组合级数 | 10 | 10 |
| 寄存器至公开输出最长组合级数 | 9 | 9 |
| 输入至公开输出最长组合级数 | 5 | 4 |

逻辑级数来自完整映射网表的连接关系；目标频率使用器件布局布线后的时序报告确认。
