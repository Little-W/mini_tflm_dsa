# FPGA 映射与资源检查

## 组合模块映射检查

`test_abc9_leaves.py` 检查完整模块的独立 ABC9 映射、相同布尔函数的计算复用，以及映射结果合并前的逐模块等价证明。需要 Python、Pyosys、Yosys 对应的 ABC 可执行文件。

```sh
python3 test/fpga_mapping/test_abc9_leaves.py --out build/abc9_leaf_tests
```

六组检查覆盖组合模块筛选、结构签名、常量与缓冲连接、端口与属性保存、未选择父模块的完整保存，以及非等价函数的拒绝。结构签名按输入端口和每一位的布尔依赖计算，支持任意宽度的 `$buf` 等值连接。输出位顺序、端口范围或逻辑关系变化均参与签名。

映射时，相同结构的函数使用一次 ABC9 结果，每个原始模块分别复制完整实现。模块实例、外部连线、端口和属性保留；每份复制结果均与对应原始模块执行 SAT 输出等价证明。所有证明通过后，工具才将模块合并回完整设计。证明使用完整确定输入，不忽略未知单元或输出差异。

## 状态模块直接连接检查

`test_direct_connections.py` 使用实际的 `vector_softmax_accumulator` 和 `parallel_prefix_add`，完成 Xilinx 7 系列技术映射，并对全部 32 位公开输出进行时序等价证明。

```sh
python3 test/fpga_mapping/test_direct_connections.py \
  --out build/direct_connection_test
```

每个映射阶段采用 `bufnorm -conn` 生成标准直接连接，并执行 `check -assert`。映射后的公开接口保持相同方向和位宽，所有通用逻辑单元均已完成技术映射。形式检查使用完整原语模型，覆盖复位、同步清零、输入流水、使能和保持行为。`summary.json` 保存源码摘要、实际 ABC9 命令、各阶段结果和证明位数。`--source-root` 可指定待检查的源码目录。

## 完整设计测量

完整 SoC 可以按固定批大小执行这一流程：

```sh
python3 scripts/fpga/open_fpga_synth.py \
  --cases soc_top --out build/open_soc \
  --abc9-batch-size 256 --abc9-isolate-leaves
```

已完成前两个综合阶段时，在相同命令后添加 `--resume`。脚本会核对源码、参数和阶段文件摘要，并从保存的 `pre_lut.il` 继续。比较两个 RTL 版本时，使用相同的映射选项与批大小。

每个批次保存完整设计检查点。`abc9_batches/progress.json` 记录已完成模块、检查点摘要、逐模块等价证明数量、实际映射的独立函数数量、运行时间及内存使用量。恢复时同时检查映射脚本、单元库和 ABC9 命令的摘要。

`metrics.json` 根据最终完整网表计算 LUT、存储器、DSP、触发器及寄存器间组合级数。目标频率由目标器件的布局布线时序报告检查。

## 功能资源分类

`function_resources.py` 从原始寄存器名称、存储器实例和输出信号确定功能归属，再沿实际组合依赖向输入方向传播。该方法适用于已经展平的完整 SoC。

```sh
python3 test/fpga_mapping/test_function_resources.py
python3 scripts/fpga/function_resources.py \
  --netlist build/open_soc/soc_top/mapped.json \
  --pre-lut build/open_soc/soc_top/pre_lut.il \
  --top soc_top \
  --out build/open_soc/soc_top/function_resources.json
```

结果将每个逻辑 LUT 计入唯一归属、多个功能共享、无法影响公开输出或未分类四项之一。四项之和与完整网表的逻辑 LUT 数严格相等。公开输出可达性分析跨越寄存器和存储器，并保守包含单元的全部输入依赖。

`functions` 同时给出各功能独占 LUT 数、涉及的共享 LUT 数，以及将共享单元等份分配后的分数结果。共享集合单独保存在 `shared_groups` 中；各功能涉及的共享数量存在重叠。精确分数分配结果的总和仍等于完整网表 LUT 数。

INV、CARRY4、触发器、DSP、BRAM 和分布式存储器按类型单独列出。`--include-cell-details` 可保存逐个 LUT 和存储单元的归属。分类结果用于选择优化区域，物理 LUT 使用量由布局布线资源报告给出。
