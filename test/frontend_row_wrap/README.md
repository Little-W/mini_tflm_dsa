# 前端行尾比较

快速位置解码使用当前位置、历史位置和历史列数计算行尾条件。
`add_equal` 接收两个操作数、输入进位和目标和值，检查完整位宽的模加法关系。
坐标值和行尾条件分别计算，接收状态同时保存相应的数据与有效信息。

公共比较模块采用普通组合 RTL。`helper.py` 调用加法等式的统一形式检查入口，
覆盖 1、2、4、8、16、28、32、33、64 位参数，包括输入进位和模运算溢出。
各个证明对操作数和目标值均不增加取值限制。

前端当前配置、窗口请求和随机背压的事务验证见
[`test/frontend_pipeline`](../frontend_pipeline/README.md)。
该测试直接检查输出数值、描述符次序、连续输出以及配置准备周期。

```bash
python3 test/frontend_row_wrap/helper.py --out build/row_wrap/helper_formal
python3 test/frontend_pipeline/run_numeric.py \
  --target asic --size 16 --lanes 16 --bus-width 64 \
  --cache-sets 16 --cache-ways 2 --line-bytes 128 --narrow-mode 2 \
  --prefetch --windowed --out build/row_wrap/numeric
```
