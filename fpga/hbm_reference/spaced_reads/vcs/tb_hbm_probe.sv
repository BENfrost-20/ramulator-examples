  // Test sequence appended after the DUT, bridge and HBM wiring.
  localparam [63:0] KERNEL_DATA = KERNEL_SLAB + GUARD_BYTES;
  localparam [63:0] HBM_DATA = HBM_SLAB + GUARD_BYTES;
  localparam [63:0] HBM_END = HBM_DATA + 4 + GUARD_BYTES;

  always #5000 kernel_clk = ~kernel_clk;
  always #1111 memory_clk = ~memory_clk;
  always #5000 ref_clk = ~ref_clk;
  initial #4700000 resetn = 1;

  genvar lane;
  generate for (lane=0; lane<32; lane=lane+1) begin: parity
    assign write_parity[lane] = ^m_wdata[lane*8 +: 8];
  end endgenerate

  reg ready_meta = 0, ready_kernel = 0;
  always @(posedge kernel_clk or negedge resetn)
    if (!resetn) begin ready_meta <= 0; ready_kernel <= 0; end
    else begin ready_meta <= apb_complete; ready_kernel <= ready_meta; end

  function automatic bit loader_address_ok(input reg [63:0] addr);
    return !$isunknown(addr) && addr[1:0] == 0 && addr >= HBM_SLAB && addr < HBM_END;
  endfunction

  task automatic write_control(input reg [7:0] addr, input reg [31:0] data);
    @(negedge kernel_clk);
    ctl_awaddr = addr; ctl_awvalid = 1;
    ctl_wdata = data; ctl_wstrb = 4'hf; ctl_wvalid = 1; ctl_bready = 1;
    fork
      begin
        do @(posedge kernel_clk); while (ctl_awready !== 1'b1);
        @(negedge kernel_clk); ctl_awvalid = 0;
      end
      begin
        do @(posedge kernel_clk); while (ctl_wready !== 1'b1);
        @(negedge kernel_clk); ctl_wvalid = 0;
      end
      begin
        do @(posedge kernel_clk); while (ctl_bvalid !== 1'b1);
        if (ctl_bresp !== 0) $fatal(1, "AXI-Lite write failed addr=%h", addr);
        @(negedge kernel_clk); ctl_bready = 0;
      end
    join
  endtask

  task automatic read_control(input reg [7:0] addr, output reg [31:0] data);
    @(negedge kernel_clk);
    ctl_araddr = addr; ctl_arvalid = 1; ctl_rready = 1;
    fork
      begin
        do @(posedge kernel_clk); while (ctl_arready !== 1'b1);
        @(negedge kernel_clk); ctl_arvalid = 0;
      end
      begin
        do @(posedge kernel_clk); while (ctl_rvalid !== 1'b1);
        if (ctl_rresp !== 0) $fatal(1, "AXI-Lite read failed addr=%h", addr);
        data = ctl_rdata;
        @(negedge kernel_clk); ctl_rready = 0;
      end
    join
  endtask

  task automatic read_counter(input reg [7:0] addr, output reg [63:0] data);
    read_control(addr, data[31:0]);
    read_control(addr + 8'd4, data[63:32]);
  endtask

  integer axi_log, native_log, results_log;
  bit measure = 0, started = 0, previous_done = 0, seen_done = 0;
  longint unsigned axi_cycle = 0, start_cycle = 0, done_cycle = 0;
  integer ar_count = 0, r_count = 0, aw_count = 0, w_count = 0, b_count = 0;

  task automatic trace(input string name, input bit has_address,
                       input reg [63:0] address, input integer id);
    if (!started) $fatal(1, "Kernel handshake before accepted start: %s", name);
    if (has_address)
      $fdisplay(axi_log, "{\"event\":\"%s\",\"n\":1,\"repetition\":0,\"axi_cycle\":%0d,\"cycles_from_start\":%0d,\"time_ps\":%0d,\"axi_addr\":%0d,\"id\":%0d}",
                name, axi_cycle, axi_cycle-start_cycle, $time, address, id);
    else
      $fdisplay(axi_log, "{\"event\":\"%s\",\"n\":1,\"repetition\":0,\"axi_cycle\":%0d,\"cycles_from_start\":%0d,\"time_ps\":%0d}",
                name, axi_cycle, axi_cycle-start_cycle, $time);
  endtask

  // Sample the same edge as the wrapper. Drive the bench only on falling edges.
  always @(posedge kernel_clk) begin
    if (!resetn) begin
      axi_cycle = 0;
      previous_done = 0;
    end else begin
      if (measure) begin
        if (ld_arvalid || ld_awvalid || ld_wvalid || ld_rready || ld_bready)
          $fatal(1, "Loader active during measurement");
        if (dut.start_core) begin
          if (started) $fatal(1, "Extra start");
          started = 1; start_cycle = axi_cycle;
        end
        if (started && dut.done_core && !previous_done) begin
          if (seen_done) $fatal(1, "Extra done");
          seen_done = 1; done_cycle = axi_cycle;
        end
        if (probe_arvalid && probe_arready) begin
          if (probe_araddr !== KERNEL_DATA || probe_arlen !== 0 ||
              probe_arsize !== 2 || probe_arburst !== 1 ||
              {probe_arid, probe_arlock, probe_arcache, probe_arprot, probe_arqos} !== 0)
            $fatal(1, "Unexpected kernel AR addr=%h", probe_araddr);
          ar_count++;
          trace("AR", 1, probe_araddr, probe_arid);
        end
        if (probe_rvalid && probe_rready) begin
          if (ar_count != 1 || s_rid[0] !== 0 || probe_rresp !== 0 ||
              probe_rlast !== 1 || probe_rdata !== WORD_IN)
            $fatal(1, "Unexpected kernel R data=%h", probe_rdata);
          r_count++;
          trace("R", 1, KERNEL_DATA, probe_rid);
        end
        if (probe_awvalid && probe_awready) begin
          if (probe_awaddr !== KERNEL_DATA || probe_awlen !== 0 ||
              probe_awsize !== 2 || probe_awburst !== 1 ||
              {probe_awid, probe_awlock, probe_awcache, probe_awprot, probe_awqos} !== 0)
            $fatal(1, "Unexpected kernel AW addr=%h", probe_awaddr);
          aw_count++;
          trace("AW", 1, probe_awaddr, probe_awid);
        end
        if (probe_wvalid && probe_wready) begin
          if (probe_wdata !== WORD_OUT || probe_wstrb !== 4'hf ||
              probe_wlast !== 1'b1)
            $fatal(1, "Unexpected kernel W data=%h WSTRB=%h", probe_wdata, probe_wstrb);
          w_count++;
          trace("W", 0, 0, 0);
        end
        if (probe_bvalid && probe_bready) begin
          if (aw_count != 1 || w_count != 1 || s_bid[0] !== 0 || probe_bresp !== 0)
            $fatal(1, "Unexpected kernel B");
          b_count++;
          trace("B", 1, KERNEL_DATA, probe_bid);
        end
      end else if (probe_arvalid || probe_awvalid || probe_wvalid) begin
        $fatal(1, "Kernel traffic outside measurement");
      end
      previous_done = dut.done_core;
      axi_cycle++;
    end
  end

  reg [31:0] expected_masks[$], observed_masks[$];
  reg [31:0] expected_mask, observed_mask;
  task automatic trace_native(input string name, input reg [33:0] address,
                              input reg [31:0] strobe);
    if (measure)
      $fdisplay(native_log, "{\"event\":\"%s\",\"n\":1,\"repetition\":0,\"time_ps\":%0d,\"axi_addr\":%0d,\"wstrb\":%0d}",
                name, $time, address, strobe);
  endtask

  // SmartConnect presents narrow transfers on the 256-bit bus. The model
  // receives the aligned address and a full-width beat with the same WSTRB.
  always @(posedge memory_clk) if (resetn) begin
    if (cattrip === 1'b1) $fatal(1, "HBM catastrophic temperature flag");
    if (m_arvalid && m_arready) begin
      if (apb_complete !== 1 || !loader_address_ok({30'b0, m_araddr}) ||
          m_arlen !== 0 || m_arsize !== 2 || m_arburst !== 1 ||
          (measure && m_araddr !== HBM_DATA[33:0]))
        $fatal(1, "Unexpected HBM-side AR addr=%h", m_araddr);
      trace_native("AR", {m_araddr[33:5], 5'b0}, 0);
    end
    if (m_awvalid && m_awready) begin
      if (apb_complete !== 1 || !loader_address_ok({30'b0, m_awaddr}) ||
          m_awlen !== 0 || m_awsize !== 2 || m_awburst !== 1 ||
          (measure && m_awaddr !== HBM_DATA[33:0]))
        $fatal(1, "Unexpected HBM-side AW addr=%h", m_awaddr);
      expected_masks.push_back(32'hf << m_awaddr[4:0]);
      trace_native("AW", {m_awaddr[33:5], 5'b0}, 0);
    end
    if (m_wvalid && m_wready) begin
      if (apb_complete !== 1 || m_wlast !== 1) $fatal(1, "Unexpected HBM-side W");
      observed_masks.push_back(m_wstrb);
      trace_native("W", HBM_DATA[33:0], m_wstrb);
    end
    while (expected_masks.size() && observed_masks.size()) begin
      expected_mask = expected_masks.pop_front();
      observed_mask = observed_masks.pop_front();
      if (observed_mask !== expected_mask)
        $fatal(1, "HBM byte lanes WSTRB=%h expected=%h", observed_mask, expected_mask);
    end
    if (m_rvalid && m_rready) begin
      if (hbm_rid !== 0 || m_rresp !== 0 || m_rlast !== 1)
        $fatal(1, "Unexpected HBM-side R");
      trace_native("R", HBM_DATA[33:0], 0);
    end
    if (m_bvalid && m_bready) begin
      if (hbm_bid !== 0 || m_bresp !== 0) $fatal(1, "Unexpected HBM-side B");
      trace_native("B", HBM_DATA[33:0], 0);
    end
  end

  reg [63:0] addr, core_cycles, drain_cycles, stable_core;
  reg [31:0] status, generation, got, wanted;
  initial begin
    axi_log = $fopen("vcs-axi.jsonl", "w");
    native_log = $fopen("vcs-hbm-axi.jsonl", "w");
    if (!axi_log || !native_log) $fatal(1, "Cannot open AXI trace files");

    wait (ready_kernel === 1'b1);
    repeat (16) @(posedge kernel_clk);
    $display("HBM_READY time_ps=%0d", $time);
    read_control(8'h00, status);
    read_control(8'h04, generation);
    if (status !== 0 || generation !== 0) $fatal(1, "Unexpected reset status");

    write_control(8'h20, KERNEL_DATA[31:0]);
    write_control(8'h24, KERNEL_DATA[63:32]);
    read_control(8'h20, got);
    if (got !== KERNEL_DATA[31:0]) $fatal(1, "BASE0 low readback mismatch");
    read_control(8'h24, got);
    if (got !== KERNEL_DATA[63:32]) $fatal(1, "BASE0 high readback mismatch");
    write_control(8'h10, 1);
    for (addr=HBM_SLAB; addr<HBM_END; addr+=4)
      write32(addr, addr == HBM_DATA ? WORD_IN : 32'ha5a5a5a5);

    repeat (16) @(posedge kernel_clk);
    @(negedge kernel_clk);
    measure = 1;
    write_control(8'h00, 1);
    do begin
      read_control(8'h00, status);
      if ($isunknown(status) || status[3]) $fatal(1, "Kernel error status=%h", status);
    end while (!status[2]);
    read_control(8'h04, got);
    if (status !== 6 || got !== generation+1)
      $fatal(1, "Unexpected completion status=%h generation=%h", status, got);
    read_counter(8'h80, core_cycles);
    read_counter(8'h88, drain_cycles);
    read_counter(8'h80, stable_core);
    if (!seen_done || core_cycles !== done_cycle-start_cycle || core_cycles == 0 ||
        drain_cycles <= core_cycles || stable_core !== core_cycles)
      $fatal(1, "Invalid counter snapshot core=%0d drain=%0d", core_cycles, drain_cycles);
    if (ar_count != 1 || r_count != 1 || aw_count != 1 || w_count != 1 || b_count != 1 ||
        expected_masks.size() || observed_masks.size())
      $fatal(1, "Unexpected AXI totals AR/R/AW/W/B=%0d/%0d/%0d/%0d/%0d",
             ar_count, r_count, aw_count, w_count, b_count);
    measure = 0;

    for (addr=HBM_SLAB; addr<HBM_END; addr+=4) begin
      read32(addr, got);
      wanted = addr == HBM_DATA ? WORD_OUT : 32'ha5a5a5a5;
      if (got !== wanted)
        $fatal(1, "DATA_MISMATCH addr=%h got=%h expected=%h", addr, got, wanted);
    end
    $fclose(axi_log);
    $fclose(native_log);
    results_log = $fopen("vcs-results.jsonl", "w");
    if (!results_log) $fatal(1, "Cannot open results file");
    $fdisplay(results_log, "{\"mode\":\"vcs_amd_hbm\",\"case\":\"memory_probe_single\",\"functional_status\":\"pass\",\"n\":1,\"repetition\":0,\"core_cycles\":%0d,\"drain_cycles\":%0d,\"input_file\":\"input-1-0.bin\",\"axi_reads\":%0d,\"axi_writes\":%0d}",
              core_cycles, drain_cycles, ar_count, aw_count);
    $fclose(results_log);
    $display("HBM_PROBE_PASSED core_cycles=%0d drain_cycles=%0d", core_cycles, drain_cycles);
    $finish;
  end

  initial begin
    #900000000;
    $fatal(1, "HBM probe watchdog ready=%b start=%b done=%b AXI=%0d/%0d/%0d/%0d/%0d",
           ready_kernel, started, seen_done, ar_count, r_count, aw_count, w_count, b_count);
  end
