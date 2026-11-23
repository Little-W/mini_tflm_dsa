# Python 周期级 RTL 仿真接口

Python 接口驱动由本仓库 RTL 编译得到的 NPU 顶层模型。模型使用 `test/npu_top/tb_npu_top.sv` 中的时钟、复位和检查过程，以及 `test/dep_modules/ddr_axi_mem_model.sv` 中的 AXI 存储器模型。Python 可以逐周期推进仿真、读取状态并导出信号轨迹。

## 构建模型

需要 Linux、Python 3、Verilator、C++ 编译器和 Make。完整矩阵模型使用 `SIZE=16` 和共享 IA/PS 存储，物理存储体数量为 6～9。按工程配置生成后端：

```bash
python3 veri/python_model/build_backend.py --config config/npu_fpga.mk --jobs 1 --reference
python3 veri/python_model/run.py --list
```

`--reference` 同时构建独立的 RTL 仿真程序，供逐周期比较使用。生成文件存放在 `veri/python_model/build/` 与 `veri/python_model/backends/`。输入文件中的阵列与缓存参数需要与后端配置一致。修改 RTL 或测试平台后，应重新构建后端。

## 生成输入并运行

```bash
python3 veri/top_regression/gen_mem.py \
  --out_dir build/python_case --size 16 --ia_cache_blocks 4 \
  --ps_frame_count 16 --pcr-engine --ps_pool_bytes 49152 --ps-force-raw \
  --K 3 --N 11 --M 7 --lhs_dtype 1 --seed 42
NPU_CONFIG=config/npu_fpga.mk python3 veri/python_model/run.py --case build/python_case --single-step \
  --trace build/python_trace.csv --result build/python_result.json
```

运行结果包含测试状态、周期计数和内存比较结果。移除 `--single-step` 可让后端连续执行；`--plusarg` 可传递存储器延迟等仿真参数。源文件摘要和后端摘要保存在构建生成的 `manifest.json` 中，运行时会检查二者是否匹配。

## 周期比较

独立参考程序可使用同一组输入记录轨迹：

```bash
backend_dir=$(python3 veri/python_model/build_backend.py --config config/npu_fpga.mk --print-config | \
  python3 -c 'import json,sys; print("veri/python_model/backends/" + json.load(sys.stdin)["tag"])')
"$backend_dir/rtl_reference" \
  +INIT_MEM=build/python_case/init.mem +GOLDEN_MEM=build/python_case/golden.mem \
  +CASE_MEM=build/python_case/config.mem +PY_TRACE=build/native_trace.csv +FULL_MEM_CHECK
cmp build/python_trace.csv build/native_trace.csv
```

Python 模型覆盖 NPU 顶层与 AXI 存储器。每种配置分别保存构建参数和输入摘要，运行前需要选择与输入数据相同的阵列及存储参数。完整 SoC 和固件的验证使用仓库根目录的 `make vcs-soc`。
