# IA 行步长共享乘法验证

`ia_row_step_register` 将复用数量编码为七位系数，使用普通 RTL 乘法计算完整字节步长，在原配置接收边沿同时保存 tile 步长和组步长。该有状态模块保持独立综合层次。`ia_loader_ctrl` 的 tile 基地址计算使用 `ia_address_add` 并行计算部分和，再保留低段进位，输出周期保持不变。

步长结果保留 `REG_WIDTH` 位，支持现有全部参数与默认系数。小于七位的参数保持 case 常量截断后的首项匹配顺序；输入出现 `X/Z` 时保留移位与定宽加法的四态传播。RTL 通过算术表达式推断 DSP。

参考提交为 `3ff66f2b6432b0fa46c348e3cd4768ac4b16b794`。参考实现的 IA 主模块、控制模块和缓存管理模块从该提交独立载入；公共依赖与当前实现内容相同，并记录 SHA-256。

## 完整 IA 模块综合

两个配置共同使用 `SIZE=16`、`DATA_WIDTH=16`、`BUS_WIDTH=64`、`DMA_LANES=8`、`REG_WIDTH=32`、`COUNT_WIDTH=29`、`CACHE_BLOCKS=32`、`ORDERED_JOB=1`、`RAM_WORD_ADDR_WIDTH=12`、`PS_FRAME_COUNT=16`，以及 `p_dma_source_layout=1`、`p_shared_write_stage=1`、`p_register_dma_request=1`。全部公开端口参与综合，参数通过 `read_slang` 的 `-G` 选项传入。

| 指标 | SoC 配置参考 | SoC 配置当前 | 紧凑扩展参考 | 紧凑扩展当前 |
| --- | ---: | ---: | ---: | ---: |
| `COMPACT_S8` | 0 | 0 | 1 | 1 |
| 逻辑 LUT | 4,629 | 4,488 | 5,537 | 5,373 |
| 分布式存储 LUT | 12 | 12 | 20 | 20 |
| 触发器 | 2,375 | 2,375 | 2,816 | 2,816 |
| DSP48 | 6 | 9 | 10 | 13 |
| RAMB36 | 2 | 2 | 2 | 2 |
| RAMB18 | 1 | 1 | 1 | 1 |
| 寄存器之间最长组合逻辑级数 | 10 | 10 | 10 | 10 |

当前 SoC 使用 32 个普通槽位。紧凑扩展支持 32 个普通槽位或 64 个紧凑槽位。容量、加载事务、接口使能以及更新边沿保持一致。

局部步长寄存模块使用 `REG_WIDTH=32`、`SIZE=16` 时，逻辑 LUT 为 `163 → 55`，触发器保持 60 个，DSP 为 `0 → 2`。完整 IA 模块另外由 `ia_address_add` 推断一个 DSP。

工具为 Yosys `0.71+40`、`read_slang`、`synth_xilinx` 和 ABC9。完整模块使用 `--abc9-batch-size 256 --abc9-isolate-leaves`；参考与当前输入分别固定在独立目录。表中级数来自实际映射网表的寄存器起点和寄存器终点。器件 150 MHz 时序需结合布局布线延迟分析。

## 功能与周期验证

| 检查 | 结果 |
| --- | --- |
| 局部无限时序等价 | 10 组位宽与尺寸参数，294 个输出等价位全部通过 |
| 局部四态比较 | 100,040 周期，覆盖数据、模式、系数、使能和复位的 `0/1/X/Z` |
| DSP 映射后等价 | 使用完整器件仿真模型，64 个公开输出位全部通过，实际推断两个 DSP |
| 完整 IA 无限时序等价 | 5 组参数，62,285 个等价位全部通过，公开输入不增加约束 |
| 完整 IA 接口比较 | 239,923 个周期，每周期比较 40 个公开输出 |
| 数值检查 | 1,083,872 个值全部一致 |

完整 IA 形式参数覆盖当前 SoC 配置、紧凑扩展、32 位计数、32 位与 128 位总线，以及通用调度配置。局部位宽覆盖 `2/3/4/5/6/7/8/16/32/64` 位，检查窄参数常量截断、默认系数、结果溢出、输出保持和异步复位。

完整事务测试包含普通与有序预取、分组任务、S8/S16、DMA 命令以及 PS 输出，运行时启用 C++ 未定义行为检查。参考实例与当前实例分别执行，全部公开输出在同一周期比较。

## 复现

在仓库根目录运行。需要 `python`、包含 `read_slang` 的 `pyosys`、`iverilog`、`vvp` 和配置好 C++20 编译环境的 Verilator。

```sh
ia_result=/tmp/ia_step_product
ia_verilator=verilator

python test/ia_step_product/run_local.py \
  --out "$ia_result/local"

python test/ia_step_product/run_mapped.py \
  --local "$ia_result/local" --out "$ia_result/mapped"

python test/ia_optimization/compare_formal.py \
  --reference 3ff66f2b --out "$ia_result/formal"

python test/ia_optimization/compare_interface.py \
  --reference 3ff66f2b --verilator "$ia_verilator" \
  --out "$ia_result/interface"

python test/ia_step_product/prepare_measurement.py \
  --out "$ia_result/inputs"

for ia_variant in reference current; do
  for ia_profile in soc compact; do
    python scripts/fpga/open_fpga_synth.py \
      --source-root "$ia_result/inputs/$ia_variant" \
      --case-config "$ia_result/inputs/cases.json" \
      --cases "${ia_profile}_${ia_variant}" \
      --abc9-batch-size 256 --abc9-isolate-leaves \
      --out "$ia_result/synthesis" \
      --lock-file "$ia_result/synthesis.lock"
  done
done
```

验证记录写入各目录的 `summary.json`。综合输出包括 `metrics.json`、`manifest.json` 和阶段脚本，输入目录的 `source_sha256.json` 保存参考与当前全部源码的内容摘要。
