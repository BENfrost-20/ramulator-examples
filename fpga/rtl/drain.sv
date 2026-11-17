`timescale 1ns/1ps
// AXI boundary completion, independently of the computational core's done.
// AXI4 W data is ordered, but may precede AW. Track an accepted partial W
// burst as well as completed W bursts; WLAST counts alone are insufficient.
// Lifetime counters assume fewer than 2^64 outstanding/wrapped transactions.
// Reset is allowed only when the surrounding AXI fabric is quiescent.
module fpga_drain(input wire clk,resetn,
 input wire ar,rlast,aw,w,wlast,b,
 input wire arvalid,awvalid,wvalid,rvalid,bvalid,
 input wire response_error,
 output wire accepted_idle,output wire pending_requests,
 output wire drained,output reg error);
 reg [63:0] nr,nrc,nw,nwc,nb;
 reg partial_w;
 // ar/rlast/aw/w/b are VALID && READY handshakes. wlast is qualified by w.
 // No assumption is made about relative AW/W acceptance order.
 assign accepted_idle=(nr==nrc)&&(nw==nb)&&(nwc==nb)&&!partial_w;
 assign pending_requests=arvalid||awvalid||wvalid;
 // A VALID request waiting for READY is not an accepted transaction, but must
 // prevent completion. Pending responses likewise require a quiet boundary.
 assign drained=resetn&&accepted_idle&&!pending_requests&&!rvalid&&!bvalid;
 always @(posedge clk) begin
  if(!resetn) begin
   nr<=0;nrc<=0;nw<=0;nwc<=0;nb<=0;partial_w<=0;error<=0;
  end else begin
   if(ar)nr<=nr+1;
   if(rlast)nrc<=nrc+1;
   if(aw)nw<=nw+1;
   if(w)begin
    partial_w<=!wlast;
    if(wlast)nwc<=nwc+1;
   end
   if(b)nb<=nb+1;
   if(response_error)error<=1;
  end
 end
endmodule
