# 偏置加载器同步驻留判断

偏置加载器在更新当前分组索引和所需块数的同一个时钟边沿，登记两个存储体的范围命中结果。登记逻辑使用控制器的下一状态值，并保留新装载、装载完成、初始化和存储体切换的原有优先顺序。`bias_valid`、DMA 请求与数据读取保持原来的有效周期。

生产配置启用 `p_register_current_range`。共享请求索引时，装载命中与当前驻留复用登记结果。WS 缓存命中使用模加相等比较，减少从读取地址减法到有效信号的组合逻辑。通用缓冲区的默认配置保留独立的装载请求和当前请求。

## 验证命令

以下命令从仓库根目录运行。形式验证需要支持 `read_slang` 的 Pyosys；本次使用 `pyosys==0.71.post40`。四态仿真使用 Icarus Verilog 12，数值仿真使用 Verilator。

```sh
python test/bias_registered_residency/run_formal.py \
  --reference 2247144937c2fd04039b9b005151f371d6b51f8f \
  --out build/bias_registered/formal

python test/bias_read_depth/prove.py \
  --reference 2247144937c2fd04039b9b005151f371d6b51f8f \
  --out build/bias_registered/generic_buffer

python test/bias_read_depth/check_four_state.py \
  --reference 2247144937c2fd04039b9b005151f371d6b51f8f \
  --out build/bias_registered/four_state
```

`run_formal.py` 分别读取原始提交与当前版本的控制器、包装模块、缓冲区和组合运算模块。两侧使用每周期任意且相同的存储返回数据，并比较全部公开输出、缓存状态以及同步存储的地址、读写使能、字节掩码和写入数据。外部控制输入不附加约束，包含装载完成与分组切换同时发生的情况。

数值与周期比较使用两个独立工作目录。原始目录可以复用算子回归创建的 `../rtl_reference`：

```sh
python test/bias_loader_reuse/run.py \
  --repo ../rtl_reference --out build/bias_registered/reference_reuse --jobs 1 --fpga

python test/bias_loader_reuse/run.py \
  --repo . --out build/bias_registered/current_reuse --jobs 1 --fpga

python test/bias_registered_residency/compare_reuse.py \
  --reference build/bias_registered/reference_reuse/result.json \
  --current build/bias_registered/current_reuse/result.json \
  --out build/bias_registered/reuse_comparison.json
```

比较程序按仿真实例及该实例的任务调用顺序匹配全部 392 项记录，保留重复执行的任务。它检查测试配置、数值检查结果、DMA 请求数，并要求每项任务的周期数不增加。

## 普通 RTL 综合与路径分析

固定参数为 `SIZE=16`、`BUS_WIDTH=64`、`COUNT_WIDTH=29`、`GROUP_BLOCKS_MAX=32`。两次综合都保留完整偏置加载器及其数据存储：

```sh
python scripts/fpga/open_fpga_synth.py \
  --source-root ../rtl_reference \
  --case-config test/bias_registered_residency/synthesis_cases.json \
  --cases bias_loader --out build/bias_registered/reference_mapping

python scripts/fpga/open_fpga_synth.py \
  --case-config test/bias_registered_residency/synthesis_cases.json \
  --cases bias_loader --out build/bias_registered/current_mapping \
  --require-register-path-limit

python test/bias_registered_residency/analyze_paths.py \
  --mapped-case build/bias_registered/current_mapping/bias_loader \
  --out build/bias_registered/current_paths.json
```

路径分析同时检查新驻留寄存器的数据输入，防止输出路径缩短后出现更长的寄存器输入路径。输出端口使用分析图中的终点表示，综合网表和资源统计保持原样。

## 实测结果

`measurement.json` 保存测试参数、源文件摘要、逐项周期比较和验证结果。

| 项目 | 原始提交 | 当前 RTL |
| --- | ---: | ---: |
| 逻辑 LUT | 1264 | 1382 |
| 触发器 | 1152 | 1154 |
| RAMB36 | 1 | 1 |
| DSP48 | 0 | 0 |
| 模块内最长寄存器组合路径 | 11 | 10 |
| 任意寄存器到 `bias_valid` 的最长组合路径 | 7 | 5 |
| `current_block_idx` 到 `bias_valid` 的最长组合路径 | 7 | 4 |
| 新驻留寄存器输入的最长组合路径 | 不适用 | 10 |
| 392 项任务周期之和 | 193571 | 193571 |

`current_block_idx[28:5]` 到 `bias_valid` 的组合路径已消除。完整加载器的 5 个参数组合形式验证通过，默认缓冲区的 6 个参数组合形式验证通过。四态检查通过 34624 项，涉及 400056 个已知参考结果位，全部保持一致。392 项 WS/IS 数值任务全部通过，每项完成周期与 DMA 请求数均保持一致。

路径级数包含 LUT、进位和选择单元，按完整连通图计数。器件布线时延与 150 MHz 时序结果由完整 SoC 的实现报告记录。
