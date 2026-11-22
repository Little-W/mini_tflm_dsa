# IA 仲裁请求寄存与加载边界

`ia_loader` 的 `p_register_dma_request` 参数控制 DMA 仲裁请求的保存方式。参数为 `1` 时，`load_ia_req` 在时钟边沿保存当前请求资格，控制器使用 `load_ia_granted && load_ia_req` 接收外部授予。复位、`init_cfg` 和 `cache_flush` 清除尚未提交的预留。参数默认值为 `0`，独立模块可以继续使用直接请求接口；生产 `npu_top` 启用寄存请求。

`load_ia_req` 表示 DMA 资源预留。实际命令由 `ext_dma_start` 标记，需求读取与预取分别在接受边沿保存自己的完整描述符。已有缓存命中继续在模块内部完成，预取保持需求优先级。新增寄存级可以使每次外部读取的准备增加一个周期，数据返回、缓存写入以及阵列连续输出保持原有接口。

普通组、尾组和预取组分别把保存的下一加载游标与相应上限比较。比较按每组三对输入位独立求值，再归并并选择一位结果；行数比较采用相同分组方式。FPGA 综合保留实际比较结果的计算边界，事件仿真及通用配置使用完整条件表达式。

## 验证范围

完整模块证明把参考 IA 接入同样的请求寄存和授予资格接口，然后比较全部公开输出及匹配状态。有效写入数据按照实际写使能比较，其余公开控制输出逐周期比较。输入没有添加功能限制。三种配置共证明 29,173 个状态和输出位：生产配置 12,673 位，通用配置 10,271 位，小容量配置 6,229 位。直接请求参数在小容量完整模块中另通过 6,229 位比较。

加载比较覆盖 15 组完整二态输入证明和 100,000 次四态比较。下一游标的保存关系覆盖 1 至 9 位计数，行数比较覆盖 6 组尺寸和寄存位宽，并完成 144,000 次四态比较。

预取协议测试分别编译 FPGA 顺序任务配置和通用配置，每种配置运行阻塞授予及持续授予两种模式。四次运行共完成 1,012 个命令、725,760 个输出值检查、490 次预取 DMA 和 4 次等待授予时重新配置取消请求。检查覆盖缓存命中与后台预取并行、不同尾列宽度、物理槽号回绕、S8 紧凑存储、S16、打包输入、预取跨配置继续执行以及需求优先级。测试在实际命令提交时检查授予资格和完整描述符。

固定生产 NPU 使用 `SIZE=16`、64 位总线、4096 字节输入缓存、128 字节缓存行和实际共享存储参数，38 个任务与 11,118 次 INT32 结果检查全部通过，同时检查 392 次 DMA 命令的描述符。包含当前前端配置保存及 IA 请求寄存的固定源码，总执行周期为 150,496；相同依赖的参考版本为 150,229，增加 267 个周期，约 0.18%。这里的周期统计包含两项模块变更。

## 独立资源与路径

生产参数的独立映射使用 4,981 个逻辑 LUT、20 个存储 LUT，共 5,001 个标称 LUT，2,537 个触发器、28 个 DSP、2 个 RAMB36 和 1 个 RAMB18。完整连接图的寄存器间最长组合路径为 10 个单元。相同公共依赖的直接请求参考实现为 4,994 个标称 LUT、2,536 个触发器和 28 个 DSP。仲裁器输入现在由请求寄存器直接驱动，加载末项条件在该寄存器结束。

结果、源码散列、配置、形式证明范围和逐任务周期保存在 [validation.json](validation.json)。150 MHz 的实现结果需由对应完整 SoC 的器件静态时序报告确认。

## 重现

```sh
python3 test/ia_request_stage/check_boundary.py \
  --source-root . --out build/ia_request_boundary
python3 test/ia_slot_stage/check_load_boundary.py \
  --source-root . --out build/ia_load_boundary
python3 test/ia_request_stage/run_formal.py \
  --source-root . --reference-root /path/to/fixed_reference \
  --out build/ia_request_formal
python3 test/ia_request_stage/run_formal.py \
  --source-root . --reference-root /path/to/fixed_reference \
  --registered 0 --cases small --out build/ia_direct_request_formal
python3 test/ia_request_stage/run_prefetch.py \
  --source-root . --out build/ia_request_prefetch_fpga --ordered-job --fpga
python3 test/ia_request_stage/run_prefetch.py \
  --source-root . --out build/ia_request_prefetch_generic
python3 test/ia_request_stage/run_npu.py \
  --source-root . --out build/ia_request_npu
python3 test/ia_request_stage/prepare_measurement.py \
  --out build/ia_request_cases.json
python3 scripts/fpga/open_fpga_synth.py --source-root . \
  --case-config build/ia_request_cases.json --cases ia_request_stage \
  --out build/ia_request_synthesis --rtl-dsp-attributes \
  --wide-alu-dsp-budget 740 --require-register-path-limit
```
