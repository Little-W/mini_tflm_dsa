# 预取描述的同步块 RAM 映射

预取队列保留 8 项、每项 65 位的完整描述。32 位缓存行释放序号使用独立的 `regfile`，配置 `p_ram_style="block"`；32 位索引和 1 位索引有效标志使用另一个 `regfile`。两个存储体共用地址、写入使能与完整写入掩码，通过各自的 `i_*` 和 `o_*` 边界信号连接。

调用方原有的 `pf_index`、`pf_retire`、`pf_index_valid` 接收过程保持原样。综合器将 `pf_retire` 的接收寄存阶段并入块 RAM，索引和有效标志在同一时钟边沿接收。读取暂停、复位、配置更新、同址读写和未初始化内容的行为保持一致。

## 验证结果

`run.py` 从当前 RTL 和参考提交 `8720e2c7` 提取实际存储实例及接收语句，并检查其余缓存代码逐字节一致。

- 对全部 520 位存储内容与 65 位输出状态进行一步归纳检查。初始存储和输出可以取任意相同值，输入地址、数据、计数与控制信号均无协议限制。
- Icarus 四态仿真完成 263,249 个周期，覆盖 262,144 组控制信号四态组合、全部 64 组读取地址四态组合、同址读写、读取暂停，以及包含 `X/Z` 的写数据和使能。
- 每个周期分别在时钟边沿前后比较输出与全部存储内容，覆盖异步复位事件。
- 实际网表中的 `u_prefetch_retire.mem.0.0` 为一个 `RAMB18E1`，采用同钟单读单写、`READ_FIRST` 和 36 位物理端口。32 位逻辑数据占用每行的有效数据位，8 个逻辑地址完整保留。
- 块 RAM 的读取使能和时钟与索引接收寄存器直接连接同一网络。`DOA_REG`、`DOB_REG` 均为 0，原有接收阶段由块 RAM 的同步读取承担；读使能关闭时保持输出。

## 局部资源

固定 `SETS=128`、`WAYS=2`、`BUS_WIDTH=64`、`LINE_BYTES=16`、`DEMAND_DEPTH=4`，采用 `physical-cost`、`small-lut-area-cost=1`、6 输入 LUT、500 ps 连线成本和 6667 ps 映射目标。

| 资源 | 参考实现 | 当前实现 | 变化 |
|---|---:|---:|---:|
| 组合逻辑 LUT | 3210 | 3176 | −34 |
| 分布式 RAM LUT 位置 | 276 | 256 | −20 |
| 配对前 LUT 位置合计 | 3486 | 3432 | −54 |
| 触发器 | 1832 | 1800 | −32 |
| RAMB18E1 | 24 | 25 | +1 |
| RAMB36E1 | 0 | 0 | 0 |
| DSP48E1 | 0 | 0 | 0 |
| 寄存器间最大组合级数 | 12 | 13 | +1 |

这些数值来自独立缓存模块的映射结果，尚未进行物理布局。完整 SoC 的 LUT 位置数和最大组合级数使用完整设计的最终测量结果。

## 复现

环境需要带 Slang 的 Yosys Python 接口及 Icarus Verilog。

```sh
python3 test/cache_prefetch_payload/run.py \
  --out /tmp/npu_cache_prefetch_payload/behavior
python3 test/cache_prefetch_payload/measure.py \
  --out /tmp/npu_cache_prefetch_payload/measurement
python3 test/cache_prefetch_payload/collect_report.py \
  --behavior /tmp/npu_cache_prefetch_payload/behavior \
  --measurement /tmp/npu_cache_prefetch_payload/measurement \
  --out /tmp/npu_cache_prefetch_payload/measurement.json
```

测量脚本逐项综合参考与当前实现，检查实际块 RAM 引脚、读取模式及接收寄存器连接，并保存源文件 SHA-256。每项测量结束后压缩大型中间文件，核对解压内容的 SHA-256，再删除未压缩副本。默认驻留内存上限为 476 MiB，可通过 `--rss-limit-mib` 设置。

完整结果保存在 [measurement.json](measurement.json)。
