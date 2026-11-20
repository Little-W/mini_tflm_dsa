# 缓存配置允许信号的并行状态检查

`conv_windowed_cache` 把前台状态、预取状态和三个需求队列计数合并为明确宽度的状态向量。生产FPGA配置使用四个并行LUT检查这些状态，并由第五个LUT合并结果与填充状态。填充状态直接进入最后一级，其余状态至配置允许输出最多经过两级LUT。

通用实现直接检查完整状态向量。较宽的需求队列计数自动使用通用表达式，保持所有参数下的状态判断、配置接收周期和返回数据。

## 独立生产参数测量

采用128组、两路、16字节缓存行、64位总线和四项需求队列。参考提交为 `9f750ed5`。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑LUT | 3,547 | 3,586 |
| FF | 1,885 | 1,884 |
| RAM LUT | 436 | 436 |
| RAMB18E1 | 20 | 20 |
| 模块内寄存器间最长路径 | 14 | 14 |
| 填充状态至 `cfg_ready` | 3 | 1 |
| 任意寄存状态至 `cfg_ready` | 3 | 2 |

综合保留并统计实际FPGA原语。路径分析只在配置允许端口增加分析终点，实际电路中没有新增寄存器。

## 验证

形式检查从实际RTL提取修改前后的表达式，并检查文件其他部分完全一致。需求计数宽度为1、3、4、5、7时，通用实现及官方LUT6_2模型共10组所有输入取值的比较通过。

BUS32和BUS64各完成13个场景、264次接收、260次完成和4次复位取消，全部13个公开输出逐周期相同。预取队列达到8项，检查14次交换以及同时进入和离开队列的情况。

完整结果及源码、网表、脚本SHA256见 `docs/data/fpga_cache_idle_ready.json`。

## 运行命令

```sh
python3 test/cache_idle_ready/run_formal.py \
  --reference 9f750ed5 --out build/idle_ready/formal
python3 test/cache_storage/synthesis.py --fpga \
  --out build/idle_ready/synthesis/current
python3 test/cache_storage/compare.py --reference 9f750ed5 \
  --bus-widths 32 64 --profiles 4x2 --cache-sets 128 --jobs 1 \
  --fpga --verilator verilator-modern --out build/idle_ready/numeric
python3 test/cache_idle_ready/measure_paths.py \
  --reference build/word_matches/synthesis/current \
  --current build/idle_ready/synthesis/current \
  --proof build/idle_ready/formal/summary.json \
  --out build/idle_ready/paths.json
```

参考目录使用 `test/cache_work_match/README.md` 中保存或重新生成的相同生产参数结果。
