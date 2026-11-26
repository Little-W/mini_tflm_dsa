# 部分和帧调度器共享算术与切片检查

## 结构

调度器在候选帧接收时计算初始或恢复行地址，在当前行组扫描结束时计算下一组行地址。这些操作由互斥的状态条件接收，因此共用一组完整模宽加法器。行剩余量和列剩余量采用两个分段的普通算术表达式，综合工具根据目标器件选择实现资源。

准备行数及其减一结果在已有 `PREPARING` 边沿同时保存；下一阶段执行移位和向上取整。这个结构保持准备阶段和命令接收的周期。

当参数提供复用容量上限时，切片检查分别处理高位归零、低位幂次形状以及切片与复用行数的比较。高位按六位并行检查，低位形状检查保留独立组合模块边界。完整复用容量检查仍参与任务错误检查。没有容量上限的参数使用完整位宽检查。

公开端口、帧进度、存储容量和同时有效的帧数保持原有定义。未知或高阻输入使用与原表达式相同的四态计算。

## 功能验证

参考提交为 `f45a6c21`。`run.py` 使用完整参考调度器和完整当前调度器，展开并比较全部状态、公开输出和帧存储内容。所有外部输入保持自由，包括非法配置和任意反压。

| SIZE | FRAME_COUNT | MAX_REUSE_TILES | 检查模式 |
| ---: | ---: | ---: | --- |
| 1 | 1 | 1 | 通用、FPGA |
| 4 | 3 | 4 | 通用、FPGA |
| 16 | 16 | 16 | 通用、FPGA |
| 16 | 16 | 32 | 通用、FPGA |
| 16 | 16 | 0 | 通用、FPGA |
| 16 | 17 | 64 | 通用、FPGA |

十二组形式证明全部通过，共比较 37,636 个等价位。原准备行数的减一表达式作为新增保存状态的归纳关系。互斥操作在未接收周期的组合候选值可以不同，其全部接收寄存器逐周期比较。

每组参数和编译模式完成 8192 个四态周期，共 98,304 个周期。测试严格比较所有公开输出，覆盖普通任务、切片任务、反压、提前结束、复位、非法配置、未知位和高阻位；同时检查产生了有效命令和未知输出传播。

详细结果与源文件散列值见 `validation.json`。

## 映射测量

参考结构和当前结构使用相同公共依赖，包括 `54a96b45` 的公共比较器。测量为完整调度器，采用 physical-cost 映射，目标周期 6667 ps，估算连线延迟 300 ps，最大切分输入数 8。

| 配置 | 结构 | 逻辑 LUT | LUTRAM | 触发器 | DSP | 内部最长组合级数 | 切片输入至 phase |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 生产，MAX_REUSE_TILES=16 | 参考 | 1151 | 56 | 907 | 5 | 10 | 9 |
| 生产，MAX_REUSE_TILES=16 | 当前 | 1090 | 56 | 916 | 7 | 10 | 7 |
| 紧凑，MAX_REUSE_TILES=32 | 参考 | 1186 | 56 | 916 | 5 | 11 | 10 |
| 紧凑，MAX_REUSE_TILES=32 | 当前 | 1115 | 56 | 926 | 7 | 11 | 7 |

生产配置减少 61 个逻辑 LUT；紧凑配置减少 71 个逻辑 LUT。两种配置的复用行数输入至 `phase` 均由 9 级缩短为 8 级。紧凑配置的最长 11 级路径经过帧优先选择和进度存储读取。详细路径与文件散列值见 `measurement.json`。

## 复现

```bash
python test/scheduler_shared_rows/run.py --reference f45a6c21 --out build/scheduler_shared_rows_verified
python test/scheduler_shared_rows/prepare.py --reference f45a6c21 --out build/scheduler_shared_rows_inputs
python scripts/fpga/open_fpga_synth.py --case-config build/scheduler_shared_rows_inputs/cases.json --cases reference_production current_production reference_compact current_compact --out build/scheduler_shared_rows_pre --through pre_lut
python scripts/fpga/remap_fpga_luts.py --source build/scheduler_shared_rows_pre/current_production --out build/scheduler_shared_rows_current_production --delay-target-ps 6667
python test/scheduler_shared_rows/measure_paths.py --mapped build/scheduler_shared_rows_current_production/mapped.json --pre-lut build/scheduler_shared_rows_pre/current_production/pre_lut.il --out build/scheduler_shared_rows_current_production/paths.json
```

其余三个配置使用相同映射和路径统计命令，替换配置名称即可。使用独立公共依赖目录时，前两条命令可增加 `--dependency-root`。
