# Python 周期级 RTL 仿真接口

Python 接口驱动由本仓库 RTL 编译得到的 NPU 顶层模型。模型使用 `test/npu_top/tb_npu_top.sv` 中的时钟、复位和检查过程，以及 `test/dep_modules/ddr_axi_mem_model.sv` 中的 AXI 存储器模型。Python 可以逐周期推进仿真、读取状态并导出信号轨迹。

## 构建模型

需要 Linux、Python 3、Verilator、C++ 编译器和 Make。按阵列与缓存配置生成后端：

```bash
python3 veri/python_model/build_backend.py --size 4 --cache 4 --ps 8 --jobs 4 --reference
python3 veri/python_model/run.py --list
```

`--reference` 同时构建独立的 RTL 仿真程序，供逐周期比较使用。生成文件存放在 `veri/python_model/build/` 与 `veri/python_model/backends/`。输入文件中的阵列与缓存参数需要与后端配置一致。修改 RTL 或测试平台后，应重新构建后端。

## 生成输入并运行

```bash
python3 veri/top_regression/gen_mem.py \
  --out_dir build/python_case --size 4 --ia_cache_blocks 4 \
  --ps_frame_count 8 --K 3 --N 11 --M 7 --lhs_dtype 1 --seed 42
python3 veri/python_model/run.py --case build/python_case --single-step \
  --trace build/python_trace.csv --result build/python_result.json
```

运行结果包含测试状态、周期计数和内存比较结果。移除 `--single-step` 可让后端连续执行；`--plusarg` 可传递存储器延迟等仿真参数。源文件摘要和后端摘要保存在构建生成的 `manifest.json` 中，运行时会检查二者是否匹配。

## 周期比较

独立参考程序可使用同一组输入记录轨迹：

```bash
veri/python_model/backends/s4_c4_p8/rtl_reference \
  +INIT_MEM=build/python_case/init.mem +GOLDEN_MEM=build/python_case/golden.mem \
  +CASE_MEM=build/python_case/config.mem +PY_TRACE=build/native_trace.csv +FULL_MEM_CHECK
cmp build/python_trace.csv build/native_trace.csv
```

`validate_cycle_equivalence.py` 提供 `SIZE=16` 配置的批量比较，运行前需为所选缓存容量构建对应后端。Python 模型覆盖 NPU 顶层与 AXI 存储器；完整 SoC 和固件的验证使用仓库根目录的 `make vcs-soc`。
