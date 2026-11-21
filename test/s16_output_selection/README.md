# S16 输出拍选择

`vec_s16_to_fifo` 分别选择当前拍的数据与字节使能，然后合并输出有效条件。数据选择保留独立组合边界，使格式和流状态的条件在选择完成后参与输出。存储器读写端口、寄存器、初始化和背压行为保持一致。

## 验证结果

- 八组 `VLEN/BANKS/BUS_WIDTH` 参数通过完整接口归纳证明，比较全部公开输出、存储器驱动端口、控制状态、银行计数和列配置。存储读值为两侧共用的任意输入，所有驱动端口均须相同。
- 相同八组参数完成 320,008 次严格四态比较，覆盖数据、有效条件、列配置、复位和背压。
- 32 位和 64 位总线各完成 81 项数值测试，分别检查 12,392 个字节，并逐周期比较参考实现的公开输出。

生产参数为 `VLEN=16, BANKS=4, BUS_WIDTH=64`。独立映射的逻辑 LUT 从 250 个变为 251 个，寄存器与存储资源保持一致，模块内部最长寄存器路径为 6 级。完整 SoC 中从格式配置经过 FIFO、仲裁器与 DMA 的路径由整机综合检查。

参考资源版本为提交 `0c99ca79`，完整接口证明使用提交 `0097b66e`，同时覆盖列配置保存与当前拍选择。源码散列、参数、检查数量和映射结果保存在 [validation.json](validation.json)。

## 重复执行

```sh
python3 test/s16_column_metadata/run.py --source-root . \
  --out build/s16_output_selection/formal
python3 test/s16_column_metadata/run.py --source-root . --four-state \
  --out build/s16_output_selection/four_state
python3 test/writeback_bus/run.py --source-root . --reference 0c99ca79 \
  --bus-width 32 --jobs 1 --out build/s16_output_selection/bus32
python3 test/writeback_bus/run.py --source-root . --reference 0c99ca79 \
  --bus-width 64 --jobs 1 --out build/s16_output_selection/bus64
```
