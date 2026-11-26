# IA 写数据循环排列与共享存储检查

## 实现

`ia_loader` 与 `ia_loader_cache_mgr` 提供 `p_zero_masked_write_data`，默认值为 `1`。该参数规定普通十六位元素布局中未写入字节的数据表示。默认配置保留每个写端口及共享写总线的完整输出值；紧凑字节格式继续采用现有的数据表示。

生产实例在共享 RAM 和固定 PS 通道同时启用时，将该参数设为 `0`。对于 `SIZE=16`、`DATA_WIDTH=16`、`DMA_LANES=8` 和已有写命令寄存级，八个输入元素共用一份 128 位循环排列结果。第一写端口保留完整原有数据表示；第二写端口与共享写总线的有效字节由真实写掩码限定。写掩码为 `1` 的每个字节与参考设计逐位相同，未写入字节可以保留循环排列后的数据。

地址、写掩码、端口使能、请求寄存级和读返回周期保持一致。共享 RAM 的每个物理端口使用原有优先次序、地址和写掩码更新数组。写使能无效、部分掩码、零掩码、单银行配置、双银行配置、同时请求、复位及暂停均保留原有状态变化。未知控制值采用原有四态表达式。

生产连接位于 `npu_matrix_engine.u_ia_loader`，参数值为：

```systemverilog
.p_zero_masked_write_data(!(p_shared_ram_enabled && p_fixed_ps_channels))
```

## 形式检查

参考版本为 `cfbbd6bd77b4b0898306689c94ec67d3d71a00af`。全部输入逐周期自由，检查未增加配置、地址或握手限制。通用配置显式取消 `SYNTHESIS` 和 `XILINX_FPGA`，FPGA 配置显式定义二者。

| 检查范围 | 配置数 | 已证明的比较位数 | 比较内容 |
| --- | ---: | ---: | --- |
| 完整缓存管理器与完整 IA 加载器 | 16 | 104,071 | 默认参数的全部输出；生产参数的第一端口全部数据、第二端口及共享总线有效写字节；全部其他输出和状态 |
| 缓存管理器与真实共享存储控制连接 | 6 | 40,966 | 全部物理端口的使能、地址、掩码、有效写字节，以及全部 IA/PS 消费者返回与控制状态 |
| 实际 RAM 数组及返回寄存器 | 4 | 83,712 | 完整数组、所有周期的读返回、任意未启用字节数据、同址操作及无效地址 |

连接检查保留实际共享存储的地址选择、端口优先次序、容量检查和返回寄存器；物理数组的读数据使用共同的任意输入。数组检查直接读取实际 `regfile` 和 `ia_ps_role_ram`，对两侧写数据的未启用字节分别提供独立自由输入，比较所有数组内容与读返回。两部分共同验证写数据表示调整对实际存储内容和消费者的影响。

`run_memory.py` 进一步实例化实际共享 RAM 数组，执行普通格式、紧凑格式和四通道格式。每个配置运行 8,192 个周期，逐周期比较全部 3,584 个 128 位存储字及全部 IA/PS 返回，包括输入为 8 位符号扩展值或任意 16 位值、所有列起点、跨半行写入、部分掩码、显式零掩码请求、读写碰撞、无效地址、复位、暂停和未知控制。覆盖统计同时记录真实物理 RAM 已接受的写操作。

完整生产数值检查使用 `test/fpga_integration/run.py`，覆盖 38 项功能任务、31 项容量任务、15 项输出任务及 12 项紧凑格式任务。运行结果和源码摘要保存于 `validation.json`。

既有 `test/ia_tile_count/run.py` 保留独立的分块计算检查，只在完整父模块其余代码的词元比较中规范化新增参数声明及参数传递。模块文件、依赖列表和中文注释分别由 `test/rtl_layout/check.py`、`check_comments.py` 检查。

## 资源测量

完整模块采用相同生产参数和相同 `physical-cost` 映射设置：最大 LUT 输入数为 8，小 LUT 面积成本为 1，线延时参数为 300 ps，目标周期为 6,667 ps。LUT 数量包含 LUTRAM 和 SRL 的名义用量；组合级数按寄存器之间的映射单元统计。

| 模块 | 参考 LUT | 当前 LUT | 减少量 | 最长组合级数 | FF | DSP | RAMB36 / RAMB18 |
| --- | ---: | ---: | ---: | --- | ---: | ---: | --- |
| 完整 `ia_loader_cache_mgr` | 1,091 | 824 | 267 | 8 → 8 | 201 | 0 | 0 / 1 |
| 完整 `ia_loader` | 4,094 | 3,836 | 258 | 10 → 10 | 2,381 | 10 | 2 / 1 |

FF、DSP、RAM 数量保持一致，完整 IA 的 12 个 LUTRAM 用量保持一致。该改变使用组合数据排列，不增加状态或寄存级。完整参数、源码摘要和映射结果摘要见 `measurement.json`。

## 运行方法

在仓库根目录执行，环境中应提供项目使用的 Yosys、Slang、Icarus Verilog、Verilator 和 Python 依赖。

```sh
python3 test/ia_masked_write_data/run_formal.py --out build/ia_masked_write_data/formal
python3 test/ia_masked_write_data/run_closed.py --out build/ia_masked_write_data/closed
python3 test/ia_masked_write_data/run_ram_formal.py --out build/ia_masked_write_data/ram_formal
python3 test/ia_masked_write_data/run_memory.py --out build/ia_masked_write_data/memory
python3 test/fpga_integration/run.py --out build/ia_masked_write_data/production --jobs 2
python3 test/ia_masked_write_data/measure.py --out build/ia_masked_write_data/measurement
python3 test/ia_tile_count/run.py --out build/ia_masked_write_data/packed_tiles
python3 test/rtl_layout/check.py --out build/ia_masked_write_data/layout
python3 test/rtl_layout/check_comments.py --out build/ia_masked_write_data/comments
```
