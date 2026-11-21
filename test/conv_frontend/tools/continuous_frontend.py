"""构造持续提供描述符的前端数值测试，并检查完成顺序和两项在途容量。"""


def continuous_bench(text, admission="idle"):
    declaration = '''
  localparam int MAX_JOB_TILES=4096;
  int queued_descriptor[MAX_JOB_TILES][4];
  int queued_expected[MAX_JOB_TILES][SIZE][SIZE];
  int accepted_count=0, completed_count=0, done_count=0;
  int maximum_pending=0;
  longint unsigned blocked_offers=0, concurrent_offers=0, finish_captures=0, commit_captures=0;
  longint unsigned job_cycle_start=0;
'''
    text = text.replace('  logic [31:0] virtual_stride;', declaration + '  logic [31:0] virtual_stride;')
    old = '      if (wr_valid && wr_ready) begin\n        if (32\'(wr_slot)!=expected_slot)'
    new = '''      if (tile_valid && !tile_ready) blocked_offers++;
      if (tile_valid && wr_valid) concurrent_offers++;
      if (tile_valid && tile_ready) begin
        accepted_count++;
        if (g_direct.dut.tile_commit) commit_captures++;
        if (wr_valid && wr_ready && unused_wr_last) finish_captures++;
      end
      if (tile_done) begin
        done_count++;
        if (done_count>completed_count) $fatal(1,"completion precedes final output");
      end
      if (accepted_count-completed_count>maximum_pending)
        maximum_pending=accepted_count-completed_count;
      if (accepted_count-completed_count>2)
        $fatal(1,"descriptor capacity exceeded");
      if (wr_valid && wr_ready) begin
        if (completed_count>=accepted_count || completed_count>=ntiles)
          $fatal(1,"output without an accepted descriptor");
        ti=completed_count;
        active_rows=queued_descriptor[completed_count][2];
        expected_slot=queued_descriptor[completed_count][3];
        if (32'(wr_slot)!=expected_slot)'''
    if old not in text:
        raise RuntimeError('Cannot locate frontend output scoreboard')
    text = text.replace(old, new, 1)
    text = text.replace('expected[wr_row][int\'(wr_col)+l]',
                        'queued_expected[completed_count][wr_row][int\'(wr_col)+l]')
    old = '''      end
      if (cycles>64'(MAX_CYCLES))'''
    new = '''        if (unused_wr_last) begin
          if (written!=active_rows*SIZE) $fatal(1,"incomplete descriptor output");
          completed_count++;
          written=0;
          for (int row=0;row<SIZE;row++)
            for (int col=0;col<SIZE;col++) seen[row][col]=0;
        end
      end
      if (cycles>64'(MAX_CYCLES))'''
    if old not in text:
        raise RuntimeError('Cannot locate frontend completion scoreboard')
    text = text.replace(old, new, 1)
    begin = text.index('      for(ti=0;ti<ntiles;ti++) begin')
    end = text.index('      while(busy && !error)', begin)
    text = text[:begin] + '''      if (ntiles>MAX_JOB_TILES) $fatal(1,"too many queued descriptors");
      accepted_count=0;completed_count=0;done_count=0;written=0;
      for(int row=0;row<SIZE;row++) for(int col=0;col<SIZE;col++) seen[row][col]=0;
      for (int entry=0;entry<ntiles;entry++) begin
        for (int field=0;field<4;field++) begin
          rc=$fscanf(fd,"%d",queued_descriptor[entry][field]);
          if(rc!=1) $fatal(1,"bad queued descriptor");
        end
        for(int row=0;row<queued_descriptor[entry][2];row++)
          for(int col=0;col<SIZE;col++) begin
            rc=$fscanf(fd,"%d",queued_expected[entry][row][col]);
            if(rc!=1) $fatal(1,"bad queued expected output");
          end
      end
      fork
        begin : descriptor_source
          for (int offer=0;offer<ntiles;offer++) begin
            @(negedge clk);
            // 周期性间隔覆盖空闲接收以及执行期间持续保持的请求。
            if ((offer%7)==1 && expect_fault==0) begin
              tile_valid=0;
              repeat(2) @(negedge clk);
            end
            tile_p0=32'(queued_descriptor[offer][0]);
            tile_q0=32'(queued_descriptor[offer][1]);
            tile_rows=RW'(queued_descriptor[offer][2]);
            tile_slot=3'(queued_descriptor[offer][3]);
            tile_narrow=NARROW_MODE==1 || (NARROW_MODE==2 && (offer%2)!=0);
            tile_valid=1;
            do @(posedge clk); while(!tile_ready && !error);
            if(error) break;
          end
          @(negedge clk);tile_valid=0;
        end
        begin : ordered_completion
          do @(negedge clk); while(completed_count!=ntiles && !tile_error);
          if(expect_fault!=0) begin
            if(!tile_error || !error || tile_done) $fatal(1,"read error not propagated");
          end else begin
            if(tile_error || error) $fatal(1,"unexpected queued frontend error");
            while(done_count!=ntiles) @(negedge clk);
            if(accepted_count!=ntiles) $fatal(1,"descriptor acceptance count differs");
          end
        end
      join
''' + text[end:]
    marker = '    $display("RTL_FRONTEND_PASS jobs='
    index = text.index(marker)
    policy_check = ('finish_captures==0' if admission=='finish' else
                    'finish_captures!=0 || commit_captures==0')
    text = text[:index] + f'''    if(blocked_offers==0 || concurrent_offers==0 || {policy_check} || maximum_pending!=2)
      $fatal(1,"continuous scenarios blocked=%0d concurrent=%0d finish=%0d commit=%0d capacity=%0d",
        blocked_offers,concurrent_offers,finish_captures,commit_captures,maximum_pending);
    $display("FRONTEND_CONTINUOUS_PASS blocked=%0d concurrent=%0d finish_captures=%0d commit_captures=%0d capacity=%0d",
      blocked_offers,concurrent_offers,finish_captures,commit_captures,maximum_pending);
''' + text[index:]
    if admission=='idle':
        text=text.replace('        accepted_count++;', '''        if (!g_direct.dut.state[$clog2(g_direct.dut.IDLE)])
          $fatal(1,"registered descriptor accepted outside IDLE");
        accepted_count++;''')
    text=text.replace('      job_bus_start=bus_byte_count;', '      job_bus_start=bus_byte_count;job_cycle_start=cycles;')
    text=text.replace('read_bytes=%0d fault=%0d",', 'read_bytes=%0d fault=%0d cycles=%0d",')
    text=text.replace('job,ntiles,stat_hits,stat_misses,stat_read_bytes,expect_fault);',
                      'job,ntiles,stat_hits,stat_misses,stat_read_bytes,expect_fault,cycles-job_cycle_start);')
    return text
