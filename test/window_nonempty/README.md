# 窗口队列的显式非空发送条件

窗口队列在前端发送条件中显式检查 `busy`。准备完成且可用的描述符始终占用队列位置，因此该检查与已有可达状态一致。前端发送和空队列配置的互斥关系可以直接参与跨模块组合优化。

参考提交为 `8bd4b00b`。队列、DMA描述符选择与完整前端的联合原生综合得到7,996个逻辑LUT，参考实现为8,025个；两者均为3,491个FF、33个DSP和56个RAM LUT。这个测量范围保留六个周边模块的接口边界，最长寄存器间组合路径均为16级，缓存配置允许接口至请求索引的组合路径均为10级。完整SoC的实际路径使用固定源码的整机报告。

## 验证

深度2、3、4、7、8分别完成时序归纳证明，证明复位之后 `descriptor_prepared && !failed` 始终蕴含队列非空。证明使用实际参考模块的完整状态更新，不限制输入。脚本确认当前源码仅增加该非空判断，其余状态、存储内容及输出表达式保持一致。

使用官方FPGA原语的窗口DMA测试接收422个请求、完成418个请求，复位取消4个请求，比较4,457个有效数值并处理19个预期错误。连续命中、并发请求、随机等待、读取错误、配置恢复和复位均通过；1,545行驻留输出周期记录与参考实现逐行一致。

完整源码摘要、原生综合结果、具体路径及测试记录保存在 `docs/data/fpga_window_nonempty.json`。

## 重现

```sh
python3 test/window_nonempty/run_formal.py --out build/nonempty/formal
python3 test/window_dma/run.py --reference-ref 8bd4b00b --fpga \
  --verilator verilator-modern --jobs 1 --out build/nonempty/window
python3 test/window_descriptor_stage/synthesis.py --reference 8bd4b00b \
  --out build/nonempty/synthesis
python3 test/window_nonempty/measure_paths.py --source build/nonempty/synthesis \
  --out build/nonempty/paths.json
```
