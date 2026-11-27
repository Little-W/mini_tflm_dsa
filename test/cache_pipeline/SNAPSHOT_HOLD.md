# 替换快照有效位与请求接收

缓存分别准备命中与替换冲突的四种保持结果。标签命中和替换冲突形成后，选择一个保持结果，再与配置清除、快照有效状态和候选启动资格共同计算下一周期有效位。六个单比特输入的最终选择保留独立组合模块，沿用原有寄存边沿。

工作请求的容量条件提前归并，保存的地址匹配结果只参与最终请求接收选择。元数据忙碌条件独立形成提示、填充和同组访问判断，请求消费事件进入末级组合。全部逻辑采用普通 SystemVerilog 描述。

`check_snapshot_hold.py` 从两版生产 RTL 提取完整有效位更新以及元数据忙碌计算，对复位、配置、当前状态、请求资格、命中、冲突等 28 个自由二值输入进行形式证明。四态仿真包含单个未知输入、多个未知输入、全未知输入以及全高阻输入，共检查 237,570 组输入。

```bash
python3 test/cache_pipeline/check_snapshot_hold.py \
  --reference-ref 9e3e5d6a --out build/cache_snapshot_hold/verification
python3 test/cache_pipeline/run.py --fpga --bus-width 64 --read-width 64 \
  --line-bytes 16 --cache-bytes 4096 --profiles 1:2 \
  --out build/cache_snapshot_hold/protocol
```

完整 4 KiB 缓存测量使用双路、64 位总线、单项请求队列及预读请求配置。以下命令保留综合推断形成的存储器和算术单元，映射后展开模块边界并检查完整寄存器路径。

```bash
python3 scripts/fpga/open_fpga_synth.py \
  --case-config test/cache_pipeline/full_cache_mapping.json --cases cache_4k \
  --out build/cache_snapshot_hold/pre --through pre_lut
python3 scripts/fpga/remap_fpga_luts.py \
  --source build/cache_snapshot_hold/pre/cache_4k \
  --out build/cache_snapshot_hold/mapped --mode physical-cost \
  --delay-target-ps 6667 --wire-delay-ps 300 --max-lut-inputs 8 \
  --small-lut-area-cost 1 --discard-abc9-temporaries
```

组合级数用于检查结构深度。目标时钟的建立和保持时间需结合目标器件的布局布线报告检查。
