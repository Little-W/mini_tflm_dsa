# 逐层性能检查

目标加速比为 1.2，采用整数条件 `6 × NPU 周期 ≤ 5 × Gemmini 周期`。

| 测量范围 | 项数 | 达标项数 | 最小加速比 | 全部达标 |
| --- | ---: | ---: | ---: | --- |
| 完整模型逐层记录 | 68 | 68 | 1.852908× | 是 |
| 完整模型逐层记录（逐输入） | 136 | 136 | 1.852908× | 是 |

## 逐项结果

| 范围 | 项目 | NPU 周期 | Gemmini 周期 | 加速比 | 达标 | 仍需减少周期 |
| --- | --- | ---: | ---: | ---: | --- | ---: |
| model_layers | ds_cnn_kws node 0 | 27142 | 10405659 | 383.378491× | 是 | 0 |
| model_layers | ds_cnn_kws node 1 | 27078 | 10478180 | 386.962848× | 是 | 0 |
| model_layers | ds_cnn_kws node 2 | 15278 | 8034233 | 525.869420× | 是 | 0 |
| model_layers | ds_cnn_kws node 3 | 27078 | 10341729 | 381.923665× | 是 | 0 |
| model_layers | ds_cnn_kws node 4 | 15218 | 7913491 | 520.008608× | 是 | 0 |
| model_layers | ds_cnn_kws node 5 | 27078 | 10272871 | 379.380715× | 是 | 0 |
| model_layers | ds_cnn_kws node 6 | 15174 | 7884863 | 519.629827× | 是 | 0 |
| model_layers | ds_cnn_kws node 7 | 27078 | 10317710 | 381.036635× | 是 | 0 |
| model_layers | ds_cnn_kws node 8 | 15174 | 7883164 | 519.517859× | 是 | 0 |
| model_layers | ds_cnn_kws node 9 | 25624 | 1291228 | 50.391352× | 是 | 0 |
| model_layers | ds_cnn_kws node 10 | 1754 | 6664 | 3.799316× | 是 | 0 |
| model_layers | ds_cnn_kws node 11 | 7428 | 99009 | 13.329160× | 是 | 0 |
| model_layers | ds_cnn_kws node 12 | 5609 | 135171 | 24.098948× | 是 | 0 |
| model_layers | mnist_cnn node 0 | 30242 | 5415230 | 179.063223× | 是 | 0 |
| model_layers | mnist_cnn node 1 | 14668 | 1229349 | 83.811631× | 是 | 0 |
| model_layers | mnist_cnn node 2 | 30674 | 2995050 | 97.641325× | 是 | 0 |
| model_layers | mnist_cnn node 3 | 8316 | 547970 | 65.893458× | 是 | 0 |
| model_layers | mnist_cnn node 4 | 1754 | 3250 | 1.852908× | 是 | 0 |
| model_layers | mnist_cnn node 5 | 20604 | 494473 | 23.998884× | 是 | 0 |
| model_layers | mnist_cnn node 6 | 7614 | 88965 | 11.684397× | 是 | 0 |
| model_layers | mnist_cnn node 7 | 5473 | 91670 | 16.749498× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 0 | 112506 | 15042568 | 133.704585× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 1 | 56540 | 15241907 | 269.577414× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 2 | 25540 | 28518321 | 1116.613978× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 3 | 28740 | 8131878 | 282.946347× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 4 | 15298 | 14715270 | 961.908093× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 5 | 48104 | 15941981 | 331.406557× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 6 | 17946 | 14459567 | 805.726457× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 7 | 25826 | 4663378 | 180.569116× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 8 | 12702 | 7868573 | 619.475122× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 9 | 39638 | 9324634 | 235.244816× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 10 | 15436 | 7818191 | 506.490736× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 11 | 24696 | 3054440 | 123.681568× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 12 | 14182 | 4784065 | 337.333592× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 13 | 20130 | 6238196 | 309.895479× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 14 | 17706 | 4700423 | 265.470631× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 15 | 20138 | 6126969 | 304.249131× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 16 | 17854 | 4626894 | 259.151675× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 17 | 20152 | 6079041 | 301.659438× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 18 | 17684 | 4590445 | 259.581825× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 19 | 20138 | 6053147 | 300.583325× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 20 | 17690 | 4635753 | 262.055003× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 21 | 20160 | 6070647 | 301.123363× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 22 | 17854 | 4726172 | 264.712221× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 23 | 14738 | 2499726 | 169.610938× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 24 | 21534 | 3591626 | 166.788613× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 25 | 18682 | 5158538 | 276.123434× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 26 | 34398 | 3566985 | 103.697453× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 27 | 17560 | 1275487 | 72.635934× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 28 | 1754 | 3250 | 1.852908× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 29 | 7986 | 46071 | 5.768971× | 是 | 0 |
| model_layers | mobilenet_v1_vww node 30 | 5085 | 35849 | 7.049951× | 是 | 0 |
| model_layers | resnet8_cifar10 node 0 | 46906 | 13650099 | 291.009658× | 是 | 0 |
| model_layers | resnet8_cifar10 node 1 | 47566 | 13496761 | 283.748076× | 是 | 0 |
| model_layers | resnet8_cifar10 node 2 | 47300 | 14366926 | 303.740507× | 是 | 0 |
| model_layers | resnet8_cifar10 node 3 | 636414 | 37810317 | 59.411510× | 是 | 0 |
| model_layers | resnet8_cifar10 node 4 | 29412 | 7227575 | 245.735584× | 是 | 0 |
| model_layers | resnet8_cifar10 node 5 | 35182 | 8041258 | 228.561708× | 是 | 0 |
| model_layers | resnet8_cifar10 node 6 | 15732 | 7117608 | 452.428680× | 是 | 0 |
| model_layers | resnet8_cifar10 node 7 | 321022 | 19362348 | 60.314707× | 是 | 0 |
| model_layers | resnet8_cifar10 node 8 | 29530 | 4400957 | 149.033424× | 是 | 0 |
| model_layers | resnet8_cifar10 node 9 | 37562 | 5101967 | 135.827885× | 是 | 0 |
| model_layers | resnet8_cifar10 node 10 | 13366 | 4108262 | 307.366602× | 是 | 0 |
| model_layers | resnet8_cifar10 node 11 | 163326 | 9909253 | 60.671620× | 是 | 0 |
| model_layers | resnet8_cifar10 node 12 | 15672 | 743288 | 47.427769× | 是 | 0 |
| model_layers | resnet8_cifar10 node 13 | 1754 | 3250 | 1.852908× | 是 | 0 |
| model_layers | resnet8_cifar10 node 14 | 7396 | 87954 | 11.892104× | 是 | 0 |
| model_layers | resnet8_cifar10 node 15 | 5475 | 90641 | 16.555434× | 是 | 0 |

独立硬件算子计时包括传输、计算和写回；同时计算 Gemmini 完整命令与循环启动后的结果，采用较严格值检查。
模型层汇总使用同一层全部输入的整数周期之和；层是否达标同时检查每个输入。RESHAPE 节点保留在结果中。
