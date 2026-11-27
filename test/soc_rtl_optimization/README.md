# 完整SoC实现检查

`run_physical.py` 使用映射后的完整SoC网表完成LUT组合、布局、物理资源统计和引脚逻辑检查。脚本保存工具副本、输入与工具SHA256、各阶段日志和资源结果；中间文件压缩后再次校验内容摘要。

LUT 资源按实际 Slice 位置和 LUT 字母统计，同一物理位置的 5LUT 与 6LUT 计为一个位置。逻辑、分布式存储器和移位寄存器三类互不重复，默认总数上限为 55,000。全部单元必须完成布局，且通过位置合法性、功能单元内容和逻辑引脚检查。`--max-lut-sites` 可指定其他资源上限。

```sh
python test/soc_rtl_optimization/run_physical.py \
  --source build/soc_mapped/soc_top \
  --out build/soc_physical \
  --nextpnr /path/to/nextpnr-xilinx \
  --chipdb /path/to/chipdb-xc7a200tfbg484-3.bin \
  --package-pins /path/to/xc7a200tfbg484-3/package_pins.csv
```

`--resume` 在确认输入、工具和已保存网表一致后继续布局。`resources.json` 保存实际物理LUT位置数量、布局检查结果和目标频率。150MHz需要完整器件延迟模型及布线后时序分析；本脚本执行到布局阶段，分别记录该项状态。

`--through pair` 完成 LUT 配对并保存网表，可随后使用 `--resume`
继续布局。配对数量用于比较候选结构；实际物理 LUT 数量从完成布局的
`resources.json` 读取。
