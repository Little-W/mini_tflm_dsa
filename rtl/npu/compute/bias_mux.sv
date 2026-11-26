module bias_mux #( // 根据偏置选择条件，为脉动阵列提供偏置或已保存的部分和初值。
    parameter int unsigned SIZE       = 4,
    parameter int unsigned DATA_WIDTH = 32
) (
    input  logic                          bias_sleep, // 置位时使用缓存部分和作为累加初值。
    input  logic signed [DATA_WIDTH-1:0]   bias_in   [SIZE], // 各计算通道的有符号偏置初值。
    input  logic signed [DATA_WIDTH-1:0]   ps_in     [SIZE], // 各计算通道已保存的部分和。
    output logic signed [DATA_WIDTH-1:0]   sum_in    [SIZE] // 选择偏置或已有部分和得到的阵列累加初值。
);

  always_comb begin
    for (int i = 0; i < SIZE; i++) begin
      sum_in[i] = bias_sleep ? ps_in[i] : bias_in[i];
    end
  end

endmodule