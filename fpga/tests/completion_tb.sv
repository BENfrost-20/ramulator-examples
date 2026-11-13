`timescale 1ns/1ps
module completion_tb;
reg clk=0;always #5 clk=~clk;reg resetn=0;
reg [7:0] s_axi_control_awaddr=0;
reg s_axi_control_awvalid=0;
wire s_axi_control_awready;
reg [31:0] s_axi_control_wdata=0;
reg [3:0] s_axi_control_wstrb=0;
reg s_axi_control_wvalid=0;
wire s_axi_control_wready;
wire [1:0] s_axi_control_bresp;
wire s_axi_control_bvalid;
reg s_axi_control_bready=0;
reg [7:0] s_axi_control_araddr=0;
reg s_axi_control_arvalid=0;
wire s_axi_control_arready;
wire [31:0] s_axi_control_rdata;
wire [1:0] s_axi_control_rresp;
wire s_axi_control_rvalid;
reg s_axi_control_rready=0;
wire start_core,busy,core_done,drain_done;reg done_core=0;wire drained,memory_error;
wire [31:0] n;wire [127:0] bases;wire [63:0] core_cycles,drain_cycles;
fpga_control #(.BANKS(2)) dut(.*);
reg arvalid=0,arready=0,rvalid=0,rready=0,rlast_bit=0;
reg awvalid=0,awready=0,wvalid=0,wready=0,wlast_bit=0,bvalid=0,bready=0;
reg response_error=0;
wire accepted_idle,pending_requests;
wire ar=arvalid&&arready,rlast=rvalid&&rready&&rlast_bit;
wire aw=awvalid&&awready,w=wvalid&&wready,b=bvalid&&bready;
fpga_drain tracker(.clk(clk),.resetn(resetn),.ar(ar),.rlast(rlast),.aw(aw),.w(w),.wlast(wlast_bit),.b(b),
 .arvalid(arvalid),.awvalid(awvalid),.wvalid(wvalid),.rvalid(rvalid),.bvalid(bvalid),
 .response_error(response_error),.accepted_idle(accepted_idle),.pending_requests(pending_requests),.drained(drained),.error(memory_error));
// Shadow the previous implementation only to exhibit its concrete false idle.
reg [63:0] legacy_aw=0,legacy_wlast=0,legacy_b=0,legacy_ar=0,legacy_rlast=0;
wire legacy_drained=(legacy_aw==legacy_b)&&(legacy_wlast==legacy_b)&&(legacy_ar==legacy_rlast)&&!(ar||aw||(w&&wlast_bit));
always @(posedge clk)begin
 if(!resetn)begin legacy_aw<=0;legacy_wlast<=0;legacy_b<=0;legacy_ar<=0;legacy_rlast<=0;end
 else begin if(aw)legacy_aw<=legacy_aw+1;if(w&&wlast_bit)legacy_wlast<=legacy_wlast+1;if(b)legacy_b<=legacy_b+1;if(ar)legacy_ar<=legacy_ar+1;if(rlast)legacy_rlast<=legacy_rlast+1;end
end
integer edge_number=0,start_edge=0,done_edge=0,drain_edge=0;
always @(posedge clk) begin
 edge_number=edge_number+1;
 if(start_core)start_edge=edge_number;
 if(done_core && !dut.done_previous && busy)done_edge=edge_number;
 if(dut.active && core_done && drained)drain_edge=edge_number;
end
initial begin #1000000;$fatal(1,"Watchdog");end

task wr(input [7:0] address,input [31:0] value,input [3:0] strobe=15,input bit reverse=0,input [1:0] expect_resp=0);
 fork
  begin repeat(reverse?3:0)@(negedge clk);@(negedge clk);s_axi_control_awaddr=address;s_axi_control_awvalid=1;
   do @(posedge clk);while(!s_axi_control_awready);@(negedge clk);s_axi_control_awvalid=0;end
  begin repeat(reverse?0:3)@(negedge clk);@(negedge clk);s_axi_control_wdata=value;s_axi_control_wstrb=strobe;s_axi_control_wvalid=1;
   do @(posedge clk);while(!s_axi_control_wready);@(negedge clk);s_axi_control_wvalid=0;end
 join
 wait(s_axi_control_bvalid);repeat(2)@(negedge clk);
 if(s_axi_control_bresp!==expect_resp)$fatal(1,"Unexpected BRESP");
 s_axi_control_bready=1;@(posedge clk);@(negedge clk);s_axi_control_bready=0;
endtask

task rd(input [7:0] address,output [31:0] value);
 @(negedge clk);s_axi_control_araddr=address;s_axi_control_arvalid=1;
 do @(posedge clk);while(!s_axi_control_arready);
 @(negedge clk);s_axi_control_arvalid=0;
 wait(s_axi_control_rvalid);value=s_axi_control_rdata;
 repeat(2)@(negedge clk);if(s_axi_control_rdata!==value)$fatal(1,"Read changed under backpressure");
 s_axi_control_rready=1;@(posedge clk);@(negedge clk);s_axi_control_rready=0;
endtask

reg [31:0] value;reg [63:0] saved_core;
task check_busy;
 @(negedge clk);if(!busy||drain_done||drained)$fatal(1,"Premature memory completion");
endtask
task finish_check;
 wait(drain_done);@(negedge clk);
 if(busy||!drained||!accepted_idle||pending_requests)$fatal(1,"Completion state");
 if(core_cycles!==done_edge-start_edge)$fatal(1,"Core counter boundary");
 if(drain_cycles!==drain_edge-start_edge)$fatal(1,"Drain counter boundary");
endtask
initial begin
 repeat(4)@(negedge clk);resetn=1;
 // Counterexample: WVALID waiting, then non-final W accepted before any AW.
 fork
  wr(0,1);
  begin
   wait(start_core);@(negedge clk);wvalid=1;wlast_bit=0;wready=0;
   @(negedge clk);done_core=1;@(negedge clk);done_core=0;
   repeat(3)begin check_busy();if(!accepted_idle||!pending_requests)$fatal(1,"Pending versus accepted distinction");end
   @(negedge clk);wready=1;@(negedge clk);wvalid=0;wready=0;
   if(!legacy_drained)$fatal(1,"Counterexample did not reach old false-idle state");
   if(accepted_idle||drained)$fatal(1,"Accepted incomplete W-before-AW burst appears drained");
   repeat(3)check_busy();saved_core=core_cycles;
   // More W data with explicit backpressure, still no AW.
   @(negedge clk);wvalid=1;wready=0;
   repeat(3)check_busy();@(negedge clk);wready=1;@(negedge clk);wvalid=0;wready=0;
   @(negedge clk);wvalid=1;wlast_bit=1;
   repeat(2)check_busy();@(negedge clk);wready=1;@(negedge clk);wvalid=0;wready=0;
   repeat(2)check_busy();
   @(negedge clk);awvalid=1;awready=0;
   repeat(2)check_busy();@(negedge clk);awready=1;@(negedge clk);awvalid=0;awready=0;
   repeat(3)check_busy();
   @(negedge clk);bvalid=1;bready=0;
   repeat(3)check_busy();@(negedge clk);bready=1;@(negedge clk);bvalid=0;bready=0;
   if(core_cycles!==saved_core)$fatal(1,"Core snapshot changed during drain");
  end
 join
 finish_check();
 // Repeated start: AW before W, a read burst, simultaneous final R and B.
 fork
  wr(0,1,15,1);
  begin
   wait(start_core);@(negedge clk);awvalid=1;awready=1;arvalid=1;arready=1;
   @(negedge clk);awvalid=0;arvalid=0;awready=0;arready=0;
   done_core=1;@(negedge clk);done_core=0;
   wvalid=1;wready=1;wlast_bit=0;
   @(negedge clk);@(negedge clk);wlast_bit=1;
   @(negedge clk);wvalid=0;wready=0;wlast_bit=0;
   rvalid=1;rready=1;rlast_bit=0;
   @(negedge clk);@(negedge clk);rready=0;
   repeat(2)check_busy();
   @(negedge clk);rready=1;rlast_bit=1;bvalid=1;bready=1;
   @(negedge clk);rvalid=0;rready=0;rlast_bit=0;bvalid=0;bready=0;
  end
 join
 finish_check();
 // Simultaneous new transactions and completion of previous transactions.
 // A completion on this edge must not erase the concurrently accepted request.
 fork
  wr(0,1);
  begin
   wait(start_core);@(negedge clk);awvalid=1;awready=1;wvalid=1;wready=1;wlast_bit=1;arvalid=1;arready=1;
   @(negedge clk);done_core=1;bvalid=1;bready=1;rvalid=1;rready=1;rlast_bit=1;
   // Second AW/AR/W also accepted on same edge as first B/RLAST.
   @(negedge clk);done_core=0;awvalid=0;wvalid=0;arvalid=0;bvalid=0;rvalid=0;
   repeat(3)check_busy();
   @(negedge clk);bvalid=1;rvalid=1;
   @(negedge clk);bvalid=0;rvalid=0;awready=0;wready=0;arready=0;bready=0;rready=0;
  end
 join
 finish_check();
 // Sticky response error and reset after quiescence.
 @(negedge clk);response_error=1;@(negedge clk);response_error=0;
 if(!memory_error)$fatal(1,"Response error lost");
 @(negedge clk);resetn=0;repeat(3)@(negedge clk);resetn=1;
 rd(0,value);if(value!==0||!drained||memory_error)$fatal(1,"Quiescent reset");
 $display("COMPLETION TRACKER TEST PASS (legacy W-before-AW counterexample reproduced)");$finish;
end
endmodule
