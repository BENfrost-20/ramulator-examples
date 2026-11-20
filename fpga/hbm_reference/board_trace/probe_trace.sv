`timescale 1ns/1ps
module fpga_probe_trace (
    input wire clk, resetn, start, done_sample, drain_sample,
    input wire arvalid, arready, rvalid, rready, awvalid, awready,
    input wire wvalid, wready, bvalid, bready,
    input wire [63:0] araddr, awaddr,
    input wire arid, rid, awid, bid, rlast, wlast,
    input wire [3:0] wstrb,
    input wire [1:0] rresp, bresp,
    input wire [7:0] mmio_addr,
    output reg [31:0] mmio_data,
    output reg mmio_valid
);
    localparam integer N_EVENTS = 13;
    localparam [N_EVENTS-1:0] HANDSHAKES = 13'h03e;

    wire [N_EVENTS-1:0] events = {
        bvalid, rvalid, wvalid, awvalid, arvalid,
        drain_sample, done_sample,
        bvalid && bready, wvalid && wready, awvalid && awready,
        rvalid && rready, arvalid && arready, start
    };

    reg running, overflow;
    reg [N_EVENTS-1:0] seen, repeated;
    reg [31:0] cycle_index;
    reg [31:0] stamps [0:N_EVENTS-1];
    reg [63:0] read_address, write_address;
    reg [13:0] attributes;
    wire [31:0] cycle_on_edge = start ? 32'd0 : cycle_index;

    // The START edge is index zero. Retain first events until the next launch.
    // Masking with seen avoids treating a stalled VALID as a duplicate transfer.
    integer i;
    always @(posedge clk) begin
        if (!resetn) begin
            running <= 0;
            overflow <= 0;
            seen <= 0;
            repeated <= 0;
            cycle_index <= 0;
        end else if (start || running) begin
            if (start) begin
                running <= !drain_sample;
                overflow <= 0;
                seen <= events;
                repeated <= 0;
                cycle_index <= 1;
            end else begin
                seen <= seen | events;
                repeated <= repeated | (seen & events & HANDSHAKES);
                if (drain_sample) running <= 0;
                else if (&cycle_index) overflow <= 1;
                else cycle_index <= cycle_index + 1'b1;
            end

            for (i = 0; i < N_EVENTS; i = i + 1)
                if (events[i] && (start || !seen[i]))
                    stamps[i] <= cycle_on_edge;
            if (events[1] && (start || !seen[1])) begin
                read_address <= araddr;
                attributes[0] <= arid;
            end
            if (events[2] && (start || !seen[2])) begin
                attributes[1] <= rid;
                attributes[9:8] <= rresp;
                attributes[12] <= rlast;
            end
            if (events[3] && (start || !seen[3])) begin
                write_address <= awaddr;
                attributes[2] <= awid;
            end
            if (events[4] && (start || !seen[4])) begin
                attributes[7:4] <= wstrb;
                attributes[13] <= wlast;
            end
            if (events[5] && (start || !seen[5])) begin
                attributes[3] <= bid;
                attributes[11:10] <= bresp;
            end
        end
    end

    wire [7:0] stamp_offset = mmio_addr - 8'ha0;
    wire [3:0] stamp_index = stamp_offset[5:2];
    always @* begin
        mmio_valid = 1;
        mmio_data = 0;
        case (mmio_addr)
            8'h90: mmio_data = 32'h41584931; // AXI1
            8'h94: mmio_data = {19'b0, seen};
            8'h98: mmio_data = {overflow, 18'b0, repeated};
            8'hd4: if (seen[1]) mmio_data = read_address[31:0];
            8'hd8: if (seen[1]) mmio_data = read_address[63:32];
            8'hdc: if (seen[3]) mmio_data = write_address[31:0];
            8'he0: if (seen[3]) mmio_data = write_address[63:32];
            8'he4: if ((seen & HANDSHAKES) == HANDSHAKES)
                mmio_data = {18'b0, attributes};
            default: begin
                if (mmio_addr >= 8'ha0 && mmio_addr <= 8'hd0 && mmio_addr[1:0] == 0) begin
                    if (seen[stamp_index]) mmio_data = stamps[stamp_index];
                end else mmio_valid = 0;
            end
        endcase
    end
endmodule
