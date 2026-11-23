
  integer output_fd, samples=1000;
  string csv_path;
  integer ar_count=0, r_count=0, hbm_ar=0, hbm_r=0;
  bit measure=0, started=0, valid_seen=0;
  longint unsigned cycle=0, origin=0, ar_tick=0, valid_tick=0, r_tick=0, previous_r=0;
  reg [31:0] status, generation, got;
  always @(posedge kernel_clk) begin
    if (measure) begin
      if (dut.start) begin
        if (started) $fatal(1,"Duplicate start");
        started=1;
        origin=cycle+1;
      end
      if (probe_awvalid || probe_wvalid || ld_arvalid || ld_awvalid || ld_wvalid)
        $fatal(1,"Unexpected traffic during measurement");
      if (probe_arvalid && probe_arready) begin
        if (!started || ar_count != r_count || probe_araddr !== KERNEL_DATA ||
            probe_arlen !== 0 || probe_arsize !== 2 || probe_arid !== 0)
          $fatal(1,"Invalid read request");
        ar_count++;
        ar_tick=cycle-origin;
        if (ar_tick<previous_r+50) $fatal(1,"Insufficient read gap");
        valid_seen=0;
      end
      if (probe_rvalid && !valid_seen) begin
        valid_seen=1;
        valid_tick=cycle-origin;
      end
      if (probe_rvalid && probe_rready) begin
        if (ar_count != r_count+1 || s_rid[0] !== 0 || probe_rlast !== 1 ||
            probe_rresp !== 0 || probe_rdata !== WORD_IN)
          $fatal(1,"Invalid read response");
        r_count++;
        r_tick=cycle-origin;
        if (valid_tick!=r_tick || r_tick<=ar_tick) $fatal(1,"Invalid read timing");
        $fdisplay(output_fd,"%0d,%0d,%0d,%0d,%0d",r_count,ar_tick,valid_tick,r_tick,r_tick-ar_tick);
        previous_r=r_tick;
      end
    end
    cycle++;
  end

  always @(posedge memory_clk) if (measure) begin
    if (m_awvalid || m_wvalid) $fatal(1,"Unexpected HBM writes during measurement");
    if (m_arvalid && m_arready) hbm_ar++;
    if (m_rvalid && m_rready) hbm_r++;
  end

  initial begin
    if (!$value$plusargs("samples=%d",samples) || !(samples==100 || samples==1000))
      $fatal(1,"Pass +samples=100 or +samples=1000");
    if (!$value$plusargs("csv=%s",csv_path)) $fatal(1,"Pass +csv=OUTPUT.csv");
    output_fd=$fopen(csv_path,"w");
    if (!output_fd) $fatal(1,"Cannot open CSV");
    $fdisplay(output_fd,"sample,ar_cycle,rvalid_cycle,r_cycle,latency_cycles");
    wait (ready_kernel === 1'b1);
    read_control(8'h90,got);
    if (got !== 32'h52444631) $fatal(1,"Unexpected probe signature");
    read_control(8'h04,generation);
    if (generation !== 0) $fatal(1,"Unexpected generation at reset");
    write_control(8'h20,KERNEL_DATA[31:0]);
    write_control(8'h24,KERNEL_DATA[63:32]);
    write32(HBM_DATA,WORD_IN);
    repeat (16) @(negedge kernel_clk);
    measure=1;
    write_control(8'h00,1);
    wait (r_count==samples);
    @(negedge kernel_clk);
    measure=0;
    if (ar_count != samples || hbm_ar != samples || hbm_r != samples)
      $fatal(1,"Unexpected AXI counts %0d %0d %0d %0d",ar_count,r_count,hbm_ar,hbm_r);
    if (samples==1000) begin
      repeat (4) @(negedge kernel_clk);
      read_control(8'h00,status);
      read_control(8'h04,got);
      if (status !== 6 || got !== generation+1) $fatal(1,"Invalid completion status");
    end
    $fclose(output_fd);
    $display("SPACED_READS_PASS samples=%0d simulated_ps=%0t",samples,$time);
    $finish;
  end

  initial begin
    #10000000000;
    $fatal(1,"Spaced HBM probe watchdog");
  end
