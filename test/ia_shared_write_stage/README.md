# 共享存储写数据预选

`ia_loader_cache_mgr` 在已有写命令寄存级保存共享 IA 存储块需要的 128 位数据。S16 的第二个写端口访问奇数物理字；S8 紧凑存储只使用第一个端口。共享存储块接收预选结果后，每个 128 位数据段只需选择 IA 数据或部分和数据。

`p_shared_write_stage` 默认关闭。`ia_loader` 将该参数传给缓存管理器，并导出 `ram_shared_wr_data`。`ia_ps_channel_ram` 通过 `i_ia_shared_write_data` 接收该数据，在最多分配两个 IA 存储块的布局中使用它。两个原有 IA 写端口的地址、数据、掩码、使能及保持行为继续保留。

写入使能按原有周期复位。数据预选在原有写命令边沿采样，不增加存储写入或读取周期。关闭参数或使用本地缓存时，新增输出为零。

## 顶层连接

生产顶层将 `u_ia_loader.ram_shared_wr_data` 连接到固定通道存储模块的 `i_ia_shared_write_data`，两个实例均启用 `p_shared_write_stage`。其余 IA 写端口仍使用原来的信号连接。

## 功能验证

| 检查 | 结果 |
|---|---:|
| 预选数据和实际共享块写入关系 | 5 项无界归纳性质通过 |
| 启用参数后的完整 IA 原有接口和状态等价 | 12,374 位通过 |
| 默认关闭的缓存接口和状态等价 | 3,207 位通过 |
| 历史 IA 接口回归 | 40 个输出、180,122 周期、903,952 次数值检查通过 |
| 缓存与共享存储联合比较 | 26,504 周期、397,560 次比较通过 |
| 四态预选寄存检查 | 100,004 组、74,227 次有效数据比较通过 |

归纳证明只要求第一个采样边沿复位，其他输入均可任意变化。五项性质分别检查第二端口数据选择、仅第一端口有效时的数据选择、第二端口地址最低位、双端口同时写入时第一端口地址最低位，以及实际共享存储块写入时全部 128 位数据与原选择结果相等。

联合比较覆盖 S8 紧凑、S16 和 S8 宽存储，两种 IA 存储块分配，任意合法 S16 列起点，字节掩码，所有输出的无效周期，配置切换、复位、冲突故障及重新配置。测试实际执行了 18,504 次 IA 写入、10,752 次 IA 读取、52,554 次部分和写入和 52,307 次部分和读取。

四态检查直接提取实际 RTL 的原写命令寄存和新增预选寄存部分，覆盖 `0/1/X/Z` 数据、全部双端口使能组合及复位周期。

## 物理资源比较

两个版本采用同一组串行输入寄存器和输出观察寄存器，使完整子系统能通过相同的封装引脚完成合法布局。部分和的四个通道按生产连接共享地址及使能。两个版本使用完整 SoC 相同的 LUT 成本、延迟目标、LUT 配对和布局设置。

| 项目 | 原有写数据选择 | 寄存预选 |
|---|---:|---:|
| 映射后的逻辑 LUT | 3,155 | 3,343 |
| 合法布局后的全部 LUT 位置 | 2,581 | 2,454 |
| 其中逻辑 LUT 位置 | 2,573 | 2,446 |
| 分布式存储 LUT 位置 | 8 | 8 |
| 由两个逻辑输出共用的位置 | 611 | 926 |
| 寄存器，包括测量模块的输入输出寄存器 | 2,301 | 2,429 |
| DSP48E1 | 6 | 6 |
| RAMB36E1 | 26 | 26 |
| 寄存器间最长组合逻辑级数 | 11 | 11 |

物理 LUT 位置减少 127，增加 128 个寄存器。共享存储容量保持 57,344 字节，DSP 与块存储数量保持一致。两个版本均通过合法布局及逻辑引脚映射检查。SoC 的最终资源和 150 MHz 时序使用完整实现结果确认。

## 复现

```bash
source /workspace/scratch/92f7be750f11/toolchain/env.sh
python3 test/ia_shared_write_stage/run_formal.py --out /tmp/ia_shared_write_formal
python3 test/ia_shared_write_stage/run_public.py --out /tmp/ia_shared_write_public
python3 test/ia_shared_write_stage/run_interface.py --out /tmp/ia_shared_write_interface
python3 test/ia_shared_write_stage/run_four_state.py --out /tmp/ia_shared_write_four_state
python3 test/ia_shared_write_stage/prepare_measurement.py --out /tmp/ia_shared_write_synth
python3 scripts/fpga/open_fpga_synth.py \
  --source-root "$PWD" \
  --case-config /tmp/ia_shared_write_synth/physical_cases.json \
  --cases reference registered --through pre_lut --out /tmp/ia_shared_write_synth/pre
for variant in reference registered; do
  python3 scripts/fpga/remap_fpga_luts.py \
    --source /tmp/ia_shared_write_synth/pre/$variant \
    --out /tmp/ia_shared_write_synth/mapped/$variant \
    --mode physical-cost --delay-target-ps 6667 --wire-delay-ps 500 --max-lut-inputs 6
done
python3 test/ia_shared_write_stage/run_physical.py \
  --mapped /tmp/ia_shared_write_synth/mapped \
  --xdc /tmp/ia_shared_write_synth/physical.xdc \
  --out /tmp/ia_shared_write_synth/physical \
  --nextpnr /workspace/scratch/92f7be750f11/toolchain/nextpnr-xilinx/build/nextpnr-xilinx.10357cc430a78c45 \
  --chipdb /workspace/scratch/92f7be750f11/toolchain/chipdb/chipdb-xc7a200tfbg484-3.bin
```

源码摘要、形式证明结果、接口比较结果及完整物理比较记录保存在 `measurement.json`。
