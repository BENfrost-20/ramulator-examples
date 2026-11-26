`timescale 1ns/1ps
module fpga_kernel(
(* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 ap_clk CLK", X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axi_control:m_axi_0, ASSOCIATED_RESET ap_rst_n" *) input wire ap_clk,
(* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 ap_rst_n RST", X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *) input wire ap_rst_n,
input wire [7:0] s_axi_control_awaddr,
input wire s_axi_control_awvalid,
output wire s_axi_control_awready,
input wire [31:0] s_axi_control_wdata,
input wire [3:0] s_axi_control_wstrb,
input wire s_axi_control_wvalid,
output wire s_axi_control_wready,
output wire [1:0] s_axi_control_bresp,
output wire s_axi_control_bvalid,
input wire s_axi_control_bready,
input wire [7:0] s_axi_control_araddr,
input wire s_axi_control_arvalid,
output wire s_axi_control_arready,
output wire [31:0] s_axi_control_rdata,
output wire [1:0] s_axi_control_rresp,
output wire s_axi_control_rvalid,
input wire s_axi_control_rready,
input wire m_axi_0_arready,
input wire m_axi_0_rid,
input wire [31:0] m_axi_0_rdata,
input wire [1:0] m_axi_0_rresp,
input wire m_axi_0_rlast,
input wire m_axi_0_rvalid,
input wire m_axi_0_awready,
input wire m_axi_0_wready,
input wire m_axi_0_bid,
input wire [1:0] m_axi_0_bresp,
input wire m_axi_0_bvalid,
output wire m_axi_0_arid,
output wire [63:0] m_axi_0_araddr,
output wire [7:0] m_axi_0_arlen,
output wire [2:0] m_axi_0_arsize,
output wire [1:0] m_axi_0_arburst,
output wire m_axi_0_arlock,
output wire [3:0] m_axi_0_arcache,
output wire [2:0] m_axi_0_arprot,
output wire [3:0] m_axi_0_arqos,
output wire [3:0] m_axi_0_arregion,
output wire m_axi_0_aruser,
output wire m_axi_0_arvalid,
output wire m_axi_0_rready,
output wire m_axi_0_awid,
output wire [63:0] m_axi_0_awaddr,
output wire [7:0] m_axi_0_awlen,
output wire [2:0] m_axi_0_awsize,
output wire [1:0] m_axi_0_awburst,
output wire m_axi_0_awlock,
output wire [3:0] m_axi_0_awcache,
output wire [2:0] m_axi_0_awprot,
output wire [3:0] m_axi_0_awqos,
output wire [3:0] m_axi_0_awregion,
output wire m_axi_0_awuser,
output wire m_axi_0_awvalid,
output wire [31:0] m_axi_0_wdata,
output wire [3:0] m_axi_0_wstrb,
output wire m_axi_0_wlast,
output wire m_axi_0_wvalid,
output wire m_axi_0_wuser,
output wire m_axi_0_bready
);

wire [63:0] base;
wire [31:0] index;
wire start, done_sample, drain_sample;
wire [31:0] trace_data;
wire trace_valid = s_axi_control_araddr == 8'h90 ||
                   s_axi_control_araddr == 8'h94 || s_axi_control_araddr == 8'h98;
reg done, error;
localparam IDLE=0, GAP=1, ISSUE=2, RESPONSE=3;
reg [1:0] state;
reg [9:0] sample_index;
reg [15:0] seed;
reg [10:0] gap;
reg [31:0] elapsed, address_cycle;
reg [63:0] trace [0:1023];
reg [63:0] readback;
reg [63:0] address_a;
reg [63:0] alternate_mask;

always @(posedge ap_clk) begin
  if (!ap_rst_n) begin
    address_a <= 0;
    alternate_mask <= 0;
  end else if (state == IDLE && start) begin
    address_a <= base;
    case (index)
      32'd0: alternate_mask <= 64'h100;
      32'd1: alternate_mask <= 64'h20000;
      32'd2: alternate_mask <= 64'h200;
      default: alternate_mask <= 0;
    endcase
  end
end

assign m_axi_0_araddr = address_a ^ (sample_index[0] ? alternate_mask : 64'd0);
assign m_axi_0_arvalid = state == ISSUE;
assign m_axi_0_arsize = 3'd2;
assign m_axi_0_arburst = 2'd1;
assign m_axi_0_rready = state == RESPONSE;
assign trace_data = s_axi_control_araddr == 8'h90 ? 32'h52444632 :
                    s_axi_control_araddr == 8'h94 ? readback[31:0] : readback[63:32];
always @(posedge ap_clk) begin
  readback <= trace[index[9:0]];
  if (state == RESPONSE && m_axi_0_rvalid && m_axi_0_rlast)
    trace[sample_index] <= {elapsed, address_cycle};
end

always @(posedge ap_clk) begin
  if (!ap_rst_n) begin
    state <= IDLE;
    elapsed <= 0;
    address_cycle <= 0;
    done <= 0;
    error <= 0;
    sample_index <= 0;
    seed <= 16'hace1;
    gap <= 50;
  end else begin
    done <= 0;
    if (state != IDLE) elapsed <= elapsed + 1;
    case (state)
      IDLE: if (start) begin
        state <= GAP;
        elapsed <= 0;
        error <= 0;
        sample_index <= 0;
        seed <= 16'hace1;
        gap <= 50;
      end
      GAP: if (gap == 1) state <= ISSUE;
           else gap <= gap - 1;
      ISSUE: if (m_axi_0_arready) begin
        address_cycle <= elapsed;
        state <= RESPONSE;
      end
      RESPONSE: if (m_axi_0_rvalid) begin
        if (!m_axi_0_rlast || m_axi_0_rresp != 0 ||
            m_axi_0_rid != 0 || m_axi_0_rdata != (sample_index[0] ? 32'h89abcdef : 32'h12345678)) error <= 1;
        if (m_axi_0_rlast) begin
          if (sample_index == 999) begin
            done <= 1;
            state <= IDLE;
          end else begin
            sample_index <= sample_index + 1;
            gap <= 11'd8 + {5'b0, seed[5:0]};
            seed <= {seed[0]^seed[2]^seed[3]^seed[5], seed[15:1]};
            state <= GAP;
          end
        end
      end
    endcase
  end
end
assign m_axi_0_arid = '0;
assign m_axi_0_arlen = '0;
assign m_axi_0_arlock = '0;
assign m_axi_0_arcache = '0;
assign m_axi_0_arprot = '0;
assign m_axi_0_arqos = '0;
assign m_axi_0_arregion = '0;
assign m_axi_0_aruser = '0;
assign m_axi_0_awid = '0;
assign m_axi_0_awaddr = '0;
assign m_axi_0_awlen = '0;
assign m_axi_0_awsize = '0;
assign m_axi_0_awburst = '0;
assign m_axi_0_awlock = '0;
assign m_axi_0_awcache = '0;
assign m_axi_0_awprot = '0;
assign m_axi_0_awqos = '0;
assign m_axi_0_awregion = '0;
assign m_axi_0_awuser = '0;
assign m_axi_0_awvalid = '0;
assign m_axi_0_wdata = '0;
assign m_axi_0_wstrb = '0;
assign m_axi_0_wlast = '0;
assign m_axi_0_wvalid = '0;
assign m_axi_0_wuser = '0;
assign m_axi_0_bready = '0;
fpga_control control(.clk(ap_clk),
.resetn(ap_rst_n),
.s_axi_control_awaddr(s_axi_control_awaddr),
.s_axi_control_awvalid(s_axi_control_awvalid),
.s_axi_control_awready(s_axi_control_awready),
.s_axi_control_wdata(s_axi_control_wdata),
.s_axi_control_wstrb(s_axi_control_wstrb),
.s_axi_control_wvalid(s_axi_control_wvalid),
.s_axi_control_wready(s_axi_control_wready),
.s_axi_control_bresp(s_axi_control_bresp),
.s_axi_control_bvalid(s_axi_control_bvalid),
.s_axi_control_bready(s_axi_control_bready),
.s_axi_control_araddr(s_axi_control_araddr),
.s_axi_control_arvalid(s_axi_control_arvalid),
.s_axi_control_arready(s_axi_control_arready),
.s_axi_control_rdata(s_axi_control_rdata),
.s_axi_control_rresp(s_axi_control_rresp),
.s_axi_control_rvalid(s_axi_control_rvalid),
.s_axi_control_rready(s_axi_control_rready),
.bases(base),
.n(index),
.start_core(start),
.done_core(done),
.drained(state == IDLE),
.memory_error(error),
.trace_done_sample(done_sample),
.trace_drain_sample(drain_sample),
.trace_mmio_valid(trace_valid),
.trace_mmio_data(trace_data));
endmodule
