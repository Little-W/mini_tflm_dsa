# 统一 NPU 的 GEMM 回归

`run.py` 使用本目录的 `tb_npu_top.sv`、生产 `npu_top` 和
`veri/top_regression/gen_mem.py`。每次按种子 `1000 + SIZE*10 + case_index`
生成 config/init/golden 文件，默认输出目录为 `build/conv_regression/`。

普通配置在 SIZE4、SIZE8、SIZE16 各运行六个场景，覆盖 WS/IS、S8/S16 输入、
空间与 K 尾部、逐通道量化以及 S16 输出。`--pcr` 增加两个 SIZE16 场景，
启用 `GEMPACT_PS_COMPRESS` 和默认 14 KiB 共享 IA/PS RAM，每个 bank 为 2 KiB。
这两个场景采用 R=2、W=8，并要求实际写入压缩部分和。所有场景检查整个测试内存，
同时检查 AXI 背压期间的请求稳定性、4 KiB 边界和输出地址范围。

## 运行

```sh
python3 test/conv_regression/run.py --root "$PWD" --out build/gemm_current \
  --verilator /path/to/verilator --pcr --jobs 1
```

缩小普通配置的范围可使用 `--sizes 4`。只运行共享压缩配置可使用
`--pcr --pcr-only`。完整运行包含 20 个场景。

报告记录计算周期、AXI 读请求数、读字节数、读数据拍数和写字节数。
共享压缩场景另外记录物理存储容量、部分和行数以及压缩行数。
`build.json` 保存构建参数、源文件 SHA256 和可执行文件 SHA256。
`--skip-build` 检查这些内容后复用构建，随后重新生成数据并执行测试。

## 比较两个源码版本

`--baseline-ref` 从本地 Git 对象导出指定参考提交依赖的 RTL、内存模型和
数据生成器，使用相同测试程序及种子运行两个版本，再逐项比较输出检查结果和周期统计。
参考提交需要支持所选择的配置及公共 NPU 接口。

```sh
python3 test/conv_regression/run.py --root "$PWD" --out build/gemm_compare \
  --verilator /path/to/verilator --sizes 4 --jobs 1 \
  --baseline-ref "$REFERENCE_COMMIT"
```

已有参考报告时，可以使用 `--compare /path/to/summary.json`。
`--compare` 与 `--baseline-ref` 互斥；不指定这两个参数时，仅报告当前版本的运行结果。

`build_verilator.sh` 是可选的本地工具构建脚本，固定官方 Verilator 提交，
并检查下载依赖的 SHA256。下载、构建和安装目录可通过脚本变量设置。
