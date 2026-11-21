    if (p_shared_write_stage && SIZE == 16 && DATA_WIDTH == 16) begin : g_shared_write_stage
      // 宽数据的第二端口位于奇数物理字；紧凑数据只使用第一端口。
      // 两种写命令均在原有边沿保存预选数据，使共享块只需选择 IA 或部分和。
      always_ff @(posedge clk) begin
        if (|write_en) begin
          ram_shared_wr_data <= write_en[1] ? write_data[1] : write_data[0];
        end
      end
