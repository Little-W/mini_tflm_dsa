# 可现场生成的原 GEMM / PCR 回归

`run.py` 使用仓库的真实 NPU testbench 和 `veri/top_regression/gen_mem.py`。
每次按固定种子 `1000 + SIZE*10 + case_index` 生成 config/init/golden，
没有历史向量或 summary 作为必需输入。默认输出为 `build/conv_regression/`。

标准 core 的 SIZE4/8/16 各六例，覆盖 WS/IS、s8/s16、空间尾块、per-channel 和
s16 输出。`--pcr` 再运行 SIZE16 的 PCR WS/IS，共 20 例。数值检查包含整片内存，
统计 cycles、AR requests、AR bytes、R beats 和写字节。

## 当前数值检查

```sh
python3 test/conv_regression/run.py --root "$PWD" --out build/gemm_current \
  --verilator verilator --pcr
```

## 固定上游与当前 RTL 的逐计数比较

```sh
make conv-gemm-regression VERILATOR=/path/to/verilator

python3 test/conv_regression/run.py --root "$PWD" --out build/gemm_compare \
  --verilator verilator --pcr \
  --baseline-ref 148964d180f52cb852c5a7e3d5c89773fa0a8ea5
```

`--baseline-ref` 从本地 Git 对象即时导出该提交必需的 RTL、testbench、Python
生成器和 tiling header 到 `--out/baseline_source/`。先用同一 runner、seed、SIZE
和 PCR profile 生成并运行基线，再运行当前代码，逐例比较完整输出及六项统计。
基线源文件的提交和 SHA 写入本次目录；补丁不携带源码快照。固定基线就是本补丁
的父提交，应用补丁的 Git 仓库应具有该对象；源码压缩包用户仍可运行普通数值检查。

已有自己生成的基线时，可传 `--compare /path/to/summary.json`，与
`--baseline-ref` 互斥；两个参数都不指定时只做当前数值检查，报告不声称基线一致。
缩小验证范围可用 `--sizes 4`；只跑 PCR 可用 `--pcr --pcr-only`。

`--skip-build` 要求已有本次 profile 的 `build.json`，并核对源文件/include SHA、
编译 flags 和 executable SHA；缺少证明或发现差异会拒绝。复用时保持原 manifest，
不会将当前源哈希回填旧记录来冒充新构建。即使复用 binary，也会重新生成并运行测试。

`build_verilator.sh` 是可选的本地工具构建脚本，固定官方 Verilator 提交并核对
依赖下载的 SHA。它不依赖旧工具链日志，所有下载/编译目录均由变量指定。
