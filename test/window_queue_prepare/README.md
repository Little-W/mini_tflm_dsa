# 窗口描述符预取与准备字段

窗口队列在正常等待期间保留已经准备的当前描述符字段。发送当前项时，存储器提前提供下一项；空队列接收以及发送唯一项时的并发接收直接使用新请求字段。错误恢复阶段提前把读地址选择为当前项，使队首完成返回后仍能更新准备字段。发送事件参与最终数据和写入使能选择。

`conv_window_data_select` 选择预取字段或新请求字段，`conv_window_data_enable` 决定准备寄存器是否更新。生产电路保留一个有效存储读端、原有队列深度、在途容量和寄存器阶段。

含未知控制值的仿真记录该状态，并持续使用完整读地址及条件更新语义。复位或重新配置清除这一记录。二态综合中该记录恒为零，相应辅助读端被删除。四态测试同时检查未知控制出现时和恢复后的行为。

## 验证方法

```sh
python3 test/window_queue_prepare/run_formal.py --out build/window_queue_prepare_formal
python3 test/window_queue_prepare/run_four_state.py --out build/window_queue_prepare_four_state
python3 test/window_queue/run.py --out build/window_queue_prepare_protocol \
  --case 2 4 1 --case 3 8 2 --case 4 8 3 --case 7 16 4
python3 test/window_queue_prepare/measure.py --out build/window_queue_prepare_measurement
```

形式验证独立证明队列占用、指针、在途数量、转发条件，以及正常等待时准备字段等于当前存储项的关系。完整逐周期等价随后使用已经证明的可达状态关系，覆盖任意外部请求、握手和响应输入，并比较全部公开输出。两种编译模式与四种配置共包含 16 项独立状态关系证明和 8 项完整等价证明。

四态验证覆盖普通编译和 `SYNTHESIS` 编译。每种模式运行 65536 个周期，在时钟边沿前后比较全部公开输出、原有状态寄存器、标签、列资格及描述符存储内容，共执行 262144 次完整观察。测试包含复位、配置、发送、接收和响应控制的 X/Z 值，以及含未知数据的请求。

独立事务模型在每种配置下检查 512 次连续请求和 4000 次随机停顿、错误恢复请求，四种配置共接收并完成 18048 个请求。

| 队列深度 | 响应通道 | 前端在途容量 |
| ---: | ---: | ---: |
| 2 | 4 | 1 |
| 3 | 8 | 2 |
| 4 | 8 | 3 |
| 7 | 16 | 4 |

## 资源与路径

生产队列测量使用深度 4、8 个响应通道、3 个前端在途窗口和 32 位响应列号。在 6667 ps 延迟目标、300 ps 导线延迟权重及相同 LUT 资源权重下，逻辑 LUT 从 315 减至 312；名义 LUTRAM 保持 76，触发器保持 115。`frontend_ready` 输入到准备数据寄存器数据或使能捕获端的最长路径从 4 个组合单元减至 2 个。

完整 `axi_dual_block_dma` 使用相同外围源码和参数进行比较，逻辑 LUT 从 14485 减至 14470，名义 LUTRAM 保持 224，触发器保持 7688。前端 `column_lane_allowed_q[0]` 到队列准备数据寄存器的最长实际寄存器路径从 13 个组合单元减至 10 个。该配置的完整 DMA 在其他位置仍有 13 级路径。

`validation.json` 保存验证结果及源文件 SHA-256，`measurement.json` 保存相同配置下的队列和完整 DMA 资源与路径结果。
