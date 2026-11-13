// Simulation-only passive logger. Only VALID&&READY is emitted as a transfer.
// One instance per interface/clock domain; never include in hardware source list.
module axi_trace #(parameter ID_W=1,parameter FILE="axi.jsonl")(
 input wire clk,resetn,
 input wire arvalid,arready,input wire [ID_W-1:0] arid,input wire [63:0] araddr,
 input wire [7:0] arlen,input wire [2:0] arsize,input wire [1:0] arburst,
 input wire rvalid,rready,input wire [ID_W-1:0] rid,input wire rlast,input wire [1:0] rresp,
 input wire awvalid,awready,input wire [ID_W-1:0] awid,input wire [63:0] awaddr,
 input wire [7:0] awlen,input wire [2:0] awsize,input wire [1:0] awburst,
 input wire wvalid,wready,input wire [3:0] wstrb,input wire wlast,
 input wire bvalid,bready,input wire [ID_W-1:0] bid,input wire [1:0] bresp
);
 integer fd;longint unsigned cycle=0;
 initial begin fd=$fopen(FILE,"w");if(!fd)$fatal(1,"Cannot open AXI trace");end
 final $fclose(fd);
 always @(posedge clk) begin
  if(resetn)begin
   $fwrite(fd,"{\"cycle\":%0d",cycle);
   if(arvalid&&arready)$fwrite(fd,",\"ar\":{\"id\":%0d,\"addr\":%0d,\"len\":%0d,\"size\":%0d,\"burst\":%0d}",arid,araddr,arlen,arsize,arburst);
   if(rvalid&&rready)$fwrite(fd,",\"r\":{\"id\":%0d,\"last\":%0d,\"resp\":%0d}",rid,rlast,rresp);
   if(awvalid&&awready)$fwrite(fd,",\"aw\":{\"id\":%0d,\"addr\":%0d,\"len\":%0d,\"size\":%0d,\"burst\":%0d}",awid,awaddr,awlen,awsize,awburst);
   if(wvalid&&wready)$fwrite(fd,",\"w\":{\"strb\":%0d,\"last\":%0d}",wstrb,wlast);
   if(bvalid&&bready)$fwrite(fd,",\"b\":{\"id\":%0d,\"resp\":%0d}",bid,bresp);
   $fwrite(fd,",\"stalls\":[");
   begin : stall_log
    bit comma;comma=0;
    if(arvalid&&!arready)begin $fwrite(fd,"\"ar\"");comma=1;end
    if(rvalid&&!rready)begin if(comma)$fwrite(fd,",");$fwrite(fd,"\"r\"");comma=1;end
    if(awvalid&&!awready)begin if(comma)$fwrite(fd,",");$fwrite(fd,"\"aw\"");comma=1;end
    if(wvalid&&!wready)begin if(comma)$fwrite(fd,",");$fwrite(fd,"\"w\"");comma=1;end
    if(bvalid&&!bready)begin if(comma)$fwrite(fd,",");$fwrite(fd,"\"b\"");end
   end
   $fwrite(fd,"]}\n");
  end
  cycle<=cycle+1;
 end
endmodule
