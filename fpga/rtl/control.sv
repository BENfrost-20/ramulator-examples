`timescale 1ns/1ps
// User-managed AXI-Lite, independent AW/W, coherent completion snapshots.
module fpga_control #(parameter BANKS=1)(
 input wire clk, resetn,
 input wire [7:0] s_axi_control_awaddr, input wire s_axi_control_awvalid, output wire s_axi_control_awready,
 input wire [31:0] s_axi_control_wdata, input wire [3:0] s_axi_control_wstrb,
 input wire s_axi_control_wvalid, output wire s_axi_control_wready,
 output reg [1:0] s_axi_control_bresp, output reg s_axi_control_bvalid, input wire s_axi_control_bready,
 input wire [7:0] s_axi_control_araddr, input wire s_axi_control_arvalid, output wire s_axi_control_arready,
 output reg [31:0] s_axi_control_rdata, output reg [1:0] s_axi_control_rresp,
 output reg s_axi_control_rvalid, input wire s_axi_control_rready,
 output reg start_core, input wire done_core, input wire drained, input wire memory_error,
 output reg [31:0] n, output wire [BANKS*64-1:0] bases,
 output reg busy, output reg core_done, output reg drain_done,
 output reg [63:0] core_cycles, output reg [63:0] drain_cycles
);
 reg [63:0] base [0:BANKS-1];
 genvar g; generate for(g=0;g<BANKS;g=g+1) begin assign bases[g*64+:64]=base[g]; end endgenerate
 reg aw_pending,w_pending,active,error,done_previous;
 reg [7:0] awaddr;
 reg [31:0] wdata,generation;
 reg [3:0] wstrb;
 reg [63:0] elapsed;
 wire [31:0] mask={{8{wstrb[3]}},{8{wstrb[2]}},{8{wstrb[1]}},{8{wstrb[0]}}};
 assign s_axi_control_awready=resetn && !aw_pending && !s_axi_control_bvalid;
 assign s_axi_control_wready=resetn && !w_pending && !s_axi_control_bvalid;
 assign s_axi_control_arready=resetn && !s_axi_control_rvalid;
 integer i;
 always @(posedge clk) begin
  if(!resetn) begin
   for(i=0;i<BANKS;i=i+1) base[i]<=0;
   n<=0; start_core<=0; busy<=0; active<=0; error<=0; done_previous<=0;
   core_done<=0; drain_done<=0; core_cycles<=0; drain_cycles<=0; elapsed<=0; generation<=0;
   aw_pending<=0;w_pending<=0;awaddr<=0;wdata<=0;wstrb<=0;
   s_axi_control_bvalid<=0;s_axi_control_bresp<=0;
   s_axi_control_rvalid<=0;s_axi_control_rresp<=0;s_axi_control_rdata<=0;
  end else begin
   start_core<=0; done_previous<=done_core;
   if(start_core) begin active<=1;elapsed<=0; end
   else if(active) elapsed<=elapsed+1;
   if(memory_error && busy) error<=1;
   if(active && !core_done && done_core && !done_previous) begin
    core_done<=1;core_cycles<=elapsed+1;
   end
   // Completion is deliberately separate from core_done. One quiet boundary
   // after done is required; traffic tracker includes partial W bursts and pending VALID requests.
   if(active && core_done && drained) begin
    drain_done<=1;drain_cycles<=elapsed+1;busy<=0;active<=0;
   end
   if(s_axi_control_awvalid && s_axi_control_awready) begin aw_pending<=1;awaddr<=s_axi_control_awaddr;end
   if(s_axi_control_wvalid && s_axi_control_wready) begin w_pending<=1;wdata<=s_axi_control_wdata;wstrb<=s_axi_control_wstrb;end
   if(s_axi_control_bvalid && s_axi_control_bready) s_axi_control_bvalid<=0;
   if(aw_pending && w_pending && !s_axi_control_bvalid) begin
    aw_pending<=0;w_pending<=0;s_axi_control_bvalid<=1;s_axi_control_bresp<=0;
    if(busy || awaddr[1:0]!=0) s_axi_control_bresp<=2;
    else if(awaddr==0) begin
     if(wstrb[0] && wdata[0]) begin
      busy<=1;start_core<=1;core_done<=0;drain_done<=0;error<=0;
      core_cycles<=0;drain_cycles<=0;generation<=generation+1;
     end
    end else if(awaddr==8'h10) n<=(n & ~mask)|(wdata & mask);
    else if(awaddr>=8'h20 && awaddr<8'h20+BANKS*8) begin
     if(awaddr[2]) base[(awaddr-8'h20)/8][63:32]<=(base[(awaddr-8'h20)/8][63:32]&~mask)|(wdata&mask);
     else base[(awaddr-8'h20)/8][31:0]<=(base[(awaddr-8'h20)/8][31:0]&~mask)|(wdata&mask);
    end else s_axi_control_bresp<=2;
   end
   if(s_axi_control_rvalid && s_axi_control_rready) s_axi_control_rvalid<=0;
   if(s_axi_control_arvalid && s_axi_control_arready) begin
    s_axi_control_rvalid<=1;s_axi_control_rresp<=0;s_axi_control_rdata<=0;
    case(s_axi_control_araddr)
     8'h00:s_axi_control_rdata<={28'b0,error,drain_done,core_done,busy};
     8'h04:s_axi_control_rdata<=generation;
     8'h10:s_axi_control_rdata<=n;
     8'h80:s_axi_control_rdata<=core_cycles[31:0];
     8'h84:s_axi_control_rdata<=core_cycles[63:32];
     8'h88:s_axi_control_rdata<=drain_cycles[31:0];
     8'h8c:s_axi_control_rdata<=drain_cycles[63:32];
     default: begin
      if(s_axi_control_araddr>=8'h20 && s_axi_control_araddr<8'h20+BANKS*8 && s_axi_control_araddr[1:0]==0) begin
       if(s_axi_control_araddr[2]) s_axi_control_rdata<=base[(s_axi_control_araddr-8'h20)/8][63:32];
       else s_axi_control_rdata<=base[(s_axi_control_araddr-8'h20)/8][31:0];
      end else s_axi_control_rresp<=2;
     end
    endcase
   end
  end
 end
endmodule
