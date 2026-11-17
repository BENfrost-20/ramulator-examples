`timescale 1ns/1ps
module control_tb;
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
wire start_core,busy,core_done,drain_done;reg done_core=0,drained=1,memory_error=0;
wire [31:0] n;wire [127:0] bases;wire [63:0] core_cycles,drain_cycles;
fpga_control #(.BANKS(2)) dut(.*);
integer edge_number=0,start_edge=0,done_edge=0,drain_edge=0;
always @(posedge clk) begin
 edge_number=edge_number+1;
 if(start_core)start_edge=edge_number;
 if(done_core && !dut.done_previous && busy)done_edge=edge_number;
 if(dut.active && core_done && drained)drain_edge=edge_number;
end
initial begin #1000000;$fatal(1,"Watchdog");end

task automatic wr(input [7:0] address,input [31:0] value,input [3:0] strobe=15,input bit reverse=0,input [1:0] expect_resp=0);
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

task automatic rd(input [7:0] address,output [31:0] value);
 @(negedge clk);s_axi_control_araddr=address;s_axi_control_arvalid=1;
 do @(posedge clk);while(!s_axi_control_arready);
 @(negedge clk);s_axi_control_arvalid=0;
 wait(s_axi_control_rvalid);value=s_axi_control_rdata;
 repeat(2)@(negedge clk);if(s_axi_control_rdata!==value)$fatal(1,"Read changed under backpressure");
 s_axi_control_rready=1;@(posedge clk);@(negedge clk);s_axi_control_rready=0;
endtask
reg [31:0] value;integer rep;reg [63:0] snap;
initial begin
 repeat(4)@(negedge clk);resetn=1;
 rd(0,value);if(value!==0)$fatal(1,"Reset status");
 wr(16,32'h12345678);wr(16,32'hab00,2,1);rd(16,value);if(value!==32'h1234ab78)$fatal(1,"Strobes");
 wr(32,32'h01020304);wr(36,32'h12,15,1);rd(36,value);if(value!==32'h12)$fatal(1,"64-bit base");
 for(rep=0;rep<3;rep=rep+1)begin
  drained=0;
  fork
   wr(0,1);
   begin
    wait(start_core);@(negedge clk);done_core=0;
    repeat(rep+1)@(negedge clk);done_core=1;
    @(negedge clk);done_core=0;
    repeat(5)@(negedge clk);drained=1;
   end
  join
  wait(drain_done);@(negedge clk);
  if(core_cycles!==done_edge-start_edge)$fatal(1,"Core off by one");
  if(drain_cycles!==drain_edge-start_edge)$fatal(1,"Drain off by one");
  if(busy)$fatal(1,"Busy after drain");
  snap=core_cycles;repeat(3)@(negedge clk);if(core_cycles!==snap)$fatal(1,"Snapshot not stable");
  rd(4,value);if(value!==rep+1)$fatal(1,"Generation/stale done");
 end
 // Writes while busy reject; errors retained through completion.
 drained=0;
 fork
  wr(0,1);
  begin wait(start_core);@(negedge clk);memory_error=1;wr(16,0,15,1,2);done_core=1;@(negedge clk);done_core=0;drained=1;end
 join
 wait(drain_done);rd(0,value);if(!value[3])$fatal(1,"Missing response error");
 @(negedge clk);resetn=0;repeat(3)@(negedge clk);resetn=1;memory_error=0;
 rd(0,value);if(value!==0)$fatal(1,"Restart reset");
 $display("CONTROL TEST PASS");$finish;
end
endmodule
