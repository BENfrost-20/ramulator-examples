#!/usr/bin/env python3
"""Prepare and run the inspected vector_add/HBM case, only when invoked by user.

No original project or baseline file is rewritten. Vivado export is a separate
user step. This script requires Python 3.8+ and the exact saved baseline.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET


ROOT = Path.home() / "thesis/hbm-reference-smoke"
BASELINE = Path.home() / "thesis/ramulator-main/.runs/run_20261117_164805_hbm-comparison-baseline"
MASTER_OUT = {
    "awid": 6, "awaddr": 64, "awlen": 8, "awsize": 3, "awburst": 2,
    "awlock": 1, "awcache": 4, "awprot": 3, "awqos": 4, "awvalid": 1,
    "wdata": 32, "wstrb": 4, "wlast": 1, "wvalid": 1, "bready": 1,
    "arid": 6, "araddr": 64, "arlen": 8, "arsize": 3, "arburst": 2,
    "arlock": 1, "arcache": 4, "arprot": 3, "arqos": 4, "arvalid": 1,
    "rready": 1,
}
MASTER_IN = {
    "awready": 1, "wready": 1, "bid": 6, "bresp": 2, "bvalid": 1,
    "arready": 1, "rid": 6, "rdata": 32, "rresp": 2, "rlast": 1,
    "rvalid": 1,
}
NATIVE_OUT = {
    "araddr": 34, "arburst": 2, "arcache": 4, "arlen": 4, "arlock": 2,
    "arprot": 3, "arqos": 4, "arsize": 3, "arvalid": 1,
    "awaddr": 34, "awburst": 2, "awcache": 4, "awlen": 4, "awlock": 2,
    "awprot": 3, "awqos": 4, "awsize": 3, "awvalid": 1, "bready": 1,
    "rready": 1, "wdata": 256, "wlast": 1, "wstrb": 32, "wvalid": 1,
}
NATIVE_IN = {
    "arready": 1, "awready": 1, "bresp": 2, "bvalid": 1,
    "rdata": 256, "rlast": 1, "rresp": 2, "rvalid": 1, "wready": 1,
}
OMITTED = {"awregion": 4, "arregion": 4, "awuser": 1, "aruser": 1, "wuser": 1}
BASES = [0x01000040, 0x01000100, 0x010001C0]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ports(path, module):
    """Read numeric, non-ANSI generated top declarations; fail on any mismatch."""
    text = Path(path).read_text()
    match = re.search(r"(?ms)^\s*module\s+" + re.escape(module) + r"\b.*?endmodule", text)
    if not match:
        raise ValueError("Module not found: %s in %s" % (module, path))
    result = {}
    for line in match.group().splitlines():
        if not re.match(r"^\s*(input|output|inout)\b", line):
            continue
        decl = re.fullmatch(
            r"\s*(input|output|inout)\s+(?:(?:wire|reg|logic)\s+)?"
            r"(?:\[(\d+)\s*:\s*(\d+)\]\s*)?(\w+)\s*;\s*(?://.*)?", line
        )
        if not decl:
            raise ValueError("Unsupported port declaration: " + line)
        direction, hi, lo, name = decl.groups()
        width = abs(int(hi) - int(lo)) + 1 if hi is not None else 1
        if name in result:
            raise ValueError("Duplicate port: " + name)
        result[name] = (direction, width)
    return result


def expected_ports():
    dut = {
        "clock": ("input", 1), "reset": ("input", 1),
        "start_port": ("input", 1), "cache_reset": ("input", 1),
        "vec_a": ("input", 64), "vec_b": ("input", 64), "vec_c": ("input", 64),
        "n": ("input", 32), "done_port": ("output", 1), "idle_port": ("output", 1),
    }
    bridge = {name: ("input", 1) for name in ("kernel_clk", "memory_clk", "resetn")}
    for letter in "abc":
        for field, width in MASTER_OUT.items():
            dut["m_axi_vec_" + letter + "_" + field] = ("output", width)
        for field, width in MASTER_IN.items():
            dut["m_axi_vec_" + letter + "_" + field] = ("input", width)
        for field, width in OMITTED.items():
            dut["m_axi_vec_" + letter + "_" + field] = ("output", width)
        for field in ("ruser", "buser"):
            dut["m_axi_vec_" + letter + "_" + field] = ("input", 1)
    for name in ("S_A", "S_B", "S_C", "S_LOAD"):
        for field, width in MASTER_OUT.items():
            bridge[name + "_" + field] = ("input", width)
        for field, width in MASTER_IN.items():
            bridge[name + "_" + field] = ("output", width)
    for field, width in NATIVE_OUT.items():
        bridge["M_HBM_" + field] = ("output", width)
    for field, width in NATIVE_IN.items():
        bridge["M_HBM_" + field] = ("input", width)
    return dut, bridge


def check_ports(path, module, expected):
    actual = ports(path, module)
    if actual != expected:
        differences = {
            key: {"expected": expected.get(key), "actual": actual.get(key)}
            for key in sorted(set(expected) | set(actual))
            if expected.get(key) != actual.get(key)
        }
        raise ValueError("Port contract mismatch for %s:\n%s" %
                         (module, json.dumps(differences, indent=2)))


def decl(kind, width, name):
    return "  %s %s%s;" % (kind, ("[%d:0] " % (width - 1)) if width > 1 else "", name)


def instance(module, name, connections):
    return "  %s %s (\n%s\n  );\n" % (
        module, name, ",\n".join("    .%s(%s)" % item for item in connections)
    )


def testbench(a, b, c):
    lines = [chr(96) + "timescale 1ps/1ps", "module tb_hbm_bambu;"]
    for field, width in dict(MASTER_OUT, **MASTER_IN).items():
        lines.append(decl("wire", width, "s_" + field + " [0:3]"))
    for field, width in MASTER_OUT.items():
        lines.append(decl("reg", width, "ld_" + field))
        lines.append("  assign s_%s[3] = ld_%s;" % (field, field))
    for field, width in OMITTED.items():
        lines.append(decl("wire", width, "dut_" + field + " [0:2]"))
    for field, width in dict(NATIVE_OUT, **NATIVE_IN).items():
        lines.append(decl("wire", width, "m_" + field))
    lines.append(TB_HEAD)
    for i, base in enumerate(BASES):
        lines.append("    base[%d] = 64'h%016x;" % (i, base))
    for i in range(8):
        lines.extend([
            "    input_a[%d] = 32'h%08x;" % (i, a[i] & 0xFFFFFFFF),
            "    input_b[%d] = 32'h%08x;" % (i, b[i] & 0xFFFFFFFF),
            "    input_c[%d] = 32'h%08x;" % (i, c[i] & 0xFFFFFFFF),
        ])
    for field in MASTER_OUT:
        value = "1" if field in ("awburst", "arburst", "wlast") else (
            "2" if field in ("awsize", "arsize") else "0")
        lines.append("    ld_%s = %s;" % (field, value))
    lines.append("  end\n")
    dut = [
        ("clock", "kernel_clk"), ("reset", "resetn"), ("start_port", "start"),
        ("cache_reset", "1'b0"), ("vec_a", "base[0]"), ("vec_b", "base[1]"),
        ("vec_c", "base[2]"), ("n", "32'd8"),
        ("done_port", "done"), ("idle_port", "idle"),
    ]
    for index, letter in enumerate("abc"):
        for field in dict(MASTER_OUT, **MASTER_IN):
            dut.append(("m_axi_vec_" + letter + "_" + field, "s_%s[%d]" % (field, index)))
        for field in OMITTED:
            dut.append(("m_axi_vec_" + letter + "_" + field, "dut_%s[%d]" % (field, index)))
        for field in ("ruser", "buser"):
            dut.append(("m_axi_vec_" + letter + "_" + field, "1'b0"))
    lines.append(instance("vector_add", "dut", dut))
    lines.extend(vendor_instances())
    lines.extend([TB_TASKS, TB_MONITORS, TB_RUN, "endmodule\n"])
    return "\n".join(lines)


def vendor_instances():
    lines = []
    bridge = [("kernel_clk", "kernel_clk"), ("memory_clk", "memory_clk"), ("resetn", "resetn")]
    for index, name in enumerate(("S_A", "S_B", "S_C", "S_LOAD")):
        for field in dict(MASTER_OUT, **MASTER_IN):
            bridge.append((name + "_" + field, "s_%s[%d]" % (field, index)))
    for field in dict(NATIVE_OUT, **NATIVE_IN):
        bridge.append(("M_HBM_" + field, "m_" + field))
    lines.append(instance("smoke_bridge_wrapper", "bridge", bridge))
    hbm = [
        ("HBM_REF_CLK_0", "ref_clk"), ("AXI_00_ACLK", "memory_clk"),
        ("AXI_00_ARESET_N", "resetn"),
        ("AXI_00_ARADDR", "{m_araddr[33:5], 5'b0}"),
        ("AXI_00_AWADDR", "{m_awaddr[33:5], 5'b0}"),
        ("AXI_00_ARSIZE", "3'd5"), ("AXI_00_AWSIZE", "3'd5"),
        ("AXI_00_ARID", "6'b0"), ("AXI_00_AWID", "6'b0"),
        ("AXI_00_RID", "hbm_rid"), ("AXI_00_BID", "hbm_bid"),
        ("AXI_00_WDATA_PARITY", "write_parity"),
        ("AXI_00_RDATA_PARITY", "read_parity"),
        ("APB_0_PCLK", "ref_clk"), ("APB_0_PRESET_N", "resetn"),
        ("APB_0_PWDATA", "32'b0"), ("APB_0_PADDR", "22'b0"),
        ("APB_0_PENABLE", "1'b0"), ("APB_0_PSEL", "1'b0"), ("APB_0_PWRITE", "1'b0"),
        ("APB_0_PRDATA", ""), ("APB_0_PREADY", ""), ("APB_0_PSLVERR", ""),
        ("apb_complete_0", "apb_complete"), ("DRAM_0_STAT_CATTRIP", "cattrip"),
        ("DRAM_0_STAT_TEMP", ""),
    ]
    direct = (
        "arburst arlen arvalid arready awburst awlen awvalid awready "
        "rready bready wdata wlast wstrb wvalid wready rdata rlast rresp rvalid bresp bvalid"
    ).split()
    hbm.extend(("AXI_00_" + field.upper(), "m_" + field) for field in direct)
    lines.append(instance("hbm_reference", "hbm", hbm))
    return lines


TB_HEAD = r"""
  // Explicit case-specific adaptation: one 32-bit transfer -> one aligned
  // 32-byte HBM beat. No cache, coalescing, read-modify-write, or added cycle.
  // SmartConnect already steers WDATA/WSTRB to the original byte lanes.
  // Read the complete normal-memory line; SmartConnect selects the word.
  // Only the initialized RAM ranges below may be accessed. Not an MMIO adapter.
  reg kernel_clk = 0;
  reg memory_clk = 0;
  reg ref_clk = 0;
  always #5000 kernel_clk = ~kernel_clk;
  always #1111 memory_clk = ~memory_clk;
  always #5000 ref_clk = ~ref_clk;
  reg resetn = 0;
  initial #4700000 resetn = 1;
  wire apb_complete, cattrip;
  wire [5:0] hbm_rid, hbm_bid;
  wire [31:0] write_parity, read_parity;
  genvar byte_index;
  generate for (byte_index=0; byte_index<32; byte_index=byte_index+1) begin: parity
    assign write_parity[byte_index] = ^m_wdata[byte_index*8 +: 8];
  end endgenerate

  reg ready_meta = 0, ready_kernel = 0;
  always @(posedge kernel_clk or negedge resetn)
    if (!resetn) begin ready_meta <= 0; ready_kernel <= 0; end
    else begin ready_meta <= apb_complete; ready_kernel <= ready_meta; end
  reg start = 0;
  wire done, idle;
  reg measure = 0;
  reg [63:0] base [0:2];
  reg [31:0] input_a [0:7], input_b [0:7], input_c [0:7];
  integer rd_req [0:2], rd_rsp [0:2];
  integer wr_req [0:2], wr_data [0:2], wr_rsp [0:2];
  integer n_ar = 0, n_r = 0, n_aw = 0, n_w = 0, n_b = 0;
  integer run_number = 0;
  time start_time, done_time, drain_time;
  reg [31:0] aw_masks[$], w_masks[$];
  reg [31:0] expected_mask, actual_mask;
  initial begin
"""

TB_LOADER = r"""  // The loader permits AW and W to handshake independently and never misses B.
  // Every transaction is completed before the task returns.
  task automatic write32(input reg [63:0] addr, input reg [31:0] value);
    begin
      if (!loader_address_ok(addr))
        $fatal(1, "LOADER invalid write address=%h", addr);
      @(negedge kernel_clk);
      ld_awaddr = addr; ld_wdata = value; ld_wstrb = 4'hf;
      ld_awvalid = 1; ld_wvalid = 1; ld_bready = 1;
      fork
        begin
          do @(posedge kernel_clk); while (s_awready[3] !== 1'b1);
          @(negedge kernel_clk); ld_awvalid = 0;
        end
        begin
          do @(posedge kernel_clk); while (s_wready[3] !== 1'b1);
          @(negedge kernel_clk); ld_wvalid = 0;
        end
        begin
          do @(posedge kernel_clk); while (s_bvalid[3] !== 1'b1);
          if (s_bresp[3] !== 0 || s_bid[3] !== 0)
            $fatal(1, "LOADER write response error addr=%h BRESP=%b BID=%h",
                   addr, s_bresp[3], s_bid[3]);
          @(negedge kernel_clk); ld_bready = 0;
        end
      join
    end
  endtask

  task automatic read32(input reg [63:0] addr, output reg [31:0] value);
    begin
      if (!loader_address_ok(addr))
        $fatal(1, "LOADER invalid read address=%h", addr);
      @(negedge kernel_clk);
      ld_araddr = addr; ld_arvalid = 1; ld_rready = 1;
      fork
        begin
          do @(posedge kernel_clk); while (s_arready[3] !== 1'b1);
          @(negedge kernel_clk); ld_arvalid = 0;
        end
        begin
          do @(posedge kernel_clk); while (s_rvalid[3] !== 1'b1);
          if (s_rresp[3] !== 0 || s_rid[3] !== 0 || s_rlast[3] !== 1)
            $fatal(1, "LOADER read response error addr=%h RRESP=%b RID=%h RLAST=%b",
                   addr, s_rresp[3], s_rid[3], s_rlast[3]);
          value = s_rdata[3];
          @(negedge kernel_clk); ld_rready = 0;
        end
      join
    end
  endtask

"""

TB_TASKS = r"""
  function automatic bit loader_address_ok(input reg [63:0] addr);
    integer bank;
    begin
      loader_address_ok = 0;
      if (!$isunknown(addr) && addr[1:0] === 0)
        for (bank=0; bank<3; bank=bank+1)
          if (addr >= base[bank]-64'd32 && addr < base[bank]+64'd64)
            loader_address_ok = 1;
    end
  endfunction

""" + TB_LOADER + r"""  function automatic [31:0] guard_value(input integer bank, input integer word_index);
    guard_value = 32'hb16b0000 ^ (bank << 8) ^ (word_index + 8);
  endfunction

  function automatic [31:0] expected_word(
      input integer bank, input integer word_index, input bit completed);
    if (word_index < 0 || word_index >= 8)
      expected_word = guard_value(bank, word_index);
    else if (bank == 0) expected_word = input_a[word_index];
    else if (bank == 1) expected_word = input_b[word_index];
    else if (completed) expected_word = input_a[word_index] + input_b[word_index];
    else expected_word = input_c[word_index];
  endfunction

  task automatic initialize_memory;
    integer bank, slot;
    reg [63:0] addr;
    begin
      for (bank=0; bank<3; bank=bank+1)
        for (slot=0; slot<24; slot=slot+1) begin
          addr = base[bank] - 64'd32 + slot*64'd4;
          write32(addr, expected_word(bank, slot-8, 0));
        end
    end
  endtask

  task automatic check_memory(input bit completed);
    integer bank, slot;
    reg [63:0] addr;
    reg [31:0] got, wanted;
    begin
      for (bank=0; bank<3; bank=bank+1)
        for (slot=0; slot<24; slot=slot+1) begin
          addr = base[bank] - 64'd32 + slot*64'd4;
          wanted = expected_word(bank, slot-8, completed);
          read32(addr, got);
          if (got !== wanted)
            $fatal(1, "DATA_MISMATCH run=%0d completed=%0d bank=%0d word=%0d addr=%h got=%h expected=%h",
                   run_number, completed, bank, slot-8, addr, got, wanted);
        end
      $display("MEMORY_CHECK_OK run=%0d completed=%0d words=72", run_number, completed);
    end
  endtask

  function automatic bit drained;
    drained = (rd_req[0]==8 && rd_rsp[0]==8 &&
               rd_req[1]==8 && rd_rsp[1]==8 &&
               rd_req[2]==0 && rd_rsp[2]==0 &&
               wr_req[0]==0 && wr_data[0]==0 && wr_rsp[0]==0 &&
               wr_req[1]==0 && wr_data[1]==0 && wr_rsp[1]==0 &&
               wr_req[2]==8 && wr_data[2]==8 && wr_rsp[2]==8 &&
               n_ar==16 && n_r==16 && n_aw==8 && n_w==8 && n_b==8 &&
               aw_masks.size()==0 && w_masks.size()==0);
  endfunction
"""

TB_MONITORS = r"""
  // Fail before truncation on the 64-bit side, and assert every omitted USER,
  // REGION, lock/cache/protection/QoS field used by this exact baseline.
  genvar port_index;
  generate for (port_index=0; port_index<3; port_index=port_index+1) begin: dut_checks
    always @(posedge kernel_clk) begin
      if (!resetn || !measure) begin
        rd_req[port_index] <= 0; rd_rsp[port_index] <= 0;
        wr_req[port_index] <= 0; wr_data[port_index] <= 0; wr_rsp[port_index] <= 0;
      end else begin
        if (s_arvalid[port_index] === 1'b1) begin
          if (port_index == 2 ||
              $isunknown(s_araddr[port_index]) ||
              s_araddr[port_index] < base[port_index] ||
              s_araddr[port_index] >= base[port_index]+32 ||
              s_araddr[port_index][1:0] !== 0 ||
              s_arlen[port_index] !== 0 || s_arsize[port_index] !== 2 ||
              s_arburst[port_index] !== 1 ||
              {s_arid[port_index], s_arlock[port_index], s_arcache[port_index],
               s_arprot[port_index], s_arqos[port_index], dut_arregion[port_index],
               dut_aruser[port_index]} !== 0)
            $fatal(1, "DUT unsupported AR port=%0d addr=%h", port_index, s_araddr[port_index]);
          if (s_arready[port_index]) rd_req[port_index] <= rd_req[port_index]+1;
        end
        if (s_awvalid[port_index] === 1'b1) begin
          if (port_index != 2 ||
              $isunknown(s_awaddr[port_index]) ||
              s_awaddr[port_index] < base[2] || s_awaddr[port_index] >= base[2]+32 ||
              s_awaddr[port_index][1:0] !== 0 ||
              s_awlen[port_index] !== 0 || s_awsize[port_index] !== 2 ||
              s_awburst[port_index] !== 1 ||
              {s_awid[port_index], s_awlock[port_index], s_awcache[port_index],
               s_awprot[port_index], s_awqos[port_index], dut_awregion[port_index],
               dut_awuser[port_index]} !== 0)
            $fatal(1, "DUT unsupported AW port=%0d addr=%h", port_index, s_awaddr[port_index]);
          if (s_awready[port_index]) wr_req[port_index] <= wr_req[port_index]+1;
        end
        if (s_wvalid[port_index] === 1'b1) begin
          if (port_index != 2 || s_wstrb[port_index] !== 4'hf ||
              s_wlast[port_index] !== 1 || dut_wuser[port_index] !== 0)
            $fatal(1, "DUT unsupported W port=%0d", port_index);
          if (s_wready[port_index]) wr_data[port_index] <= wr_data[port_index]+1;
        end
        if (s_rvalid[port_index] === 1'b1) begin
          if (s_rresp[port_index] !== 0 || s_rid[port_index] !== 0 ||
              s_rlast[port_index] !== 1)
            $fatal(1, "DUT read response error port=%0d", port_index);
          if (s_rready[port_index]) rd_rsp[port_index] <= rd_rsp[port_index]+1;
        end
        if (s_bvalid[port_index] === 1'b1) begin
          if (s_bresp[port_index] !== 0 || s_bid[port_index] !== 0)
            $fatal(1, "DUT write response error port=%0d", port_index);
          if (s_bready[port_index]) wr_rsp[port_index] <= wr_rsp[port_index]+1;
        end
        if (rd_req[port_index]>8 || rd_rsp[port_index]>8 ||
            wr_req[port_index]>8 || wr_data[port_index]>8 || wr_rsp[port_index]>8)
          $fatal(1, "Extra DUT traffic port=%0d", port_index);
      end
      if (resetn && !measure &&
          (s_arvalid[port_index] === 1'b1 || s_awvalid[port_index] === 1'b1 ||
           s_wvalid[port_index] === 1'b1))
        $fatal(1, "Unexpected DUT traffic outside measurement port=%0d", port_index);
    end
  end endgenerate

  integer bank_check;
  reg address_allowed;
  always @(posedge memory_clk) begin
    if (!resetn) begin
      aw_masks.delete(); w_masks.delete();
    end else begin
      if (cattrip === 1'b1) $fatal(1, "HBM catastrophic temperature flag");
      if (m_arvalid === 1'b1 || m_awvalid === 1'b1 || m_wvalid === 1'b1)
        if (apb_complete !== 1) $fatal(1, "HBM traffic before apb_complete");
      if (m_arvalid === 1'b1) begin
        address_allowed = 0;
        for (bank_check=0; bank_check<3; bank_check=bank_check+1)
          if (m_araddr >= base[bank_check]-32 && m_araddr < base[bank_check]+64)
            address_allowed = 1;
        if (!address_allowed || $isunknown(m_araddr) ||
            m_araddr[1:0] !== 0 || m_arlen !== 0 ||
            m_arsize !== 2 ||
            m_arburst !== 1 ||
            {m_arlock, m_arcache, m_arprot, m_arqos} !== 0)
          $fatal(1, "NATIVE unsupported AR addr=%h size=%h len=%h sidebands=%h",
                 m_araddr, m_arsize, m_arlen, {m_arlock,m_arcache,m_arprot,m_arqos});
      end
      if (m_awvalid === 1'b1) begin
        address_allowed = 0;
        for (bank_check=0; bank_check<3; bank_check=bank_check+1)
          if (m_awaddr >= base[bank_check]-32 && m_awaddr < base[bank_check]+64)
            address_allowed = 1;
        if (!address_allowed || $isunknown(m_awaddr) ||
            m_awaddr[1:0] !== 0 || m_awlen !== 0 ||
            m_awsize !== 2 ||
            m_awburst !== 1 ||
            {m_awlock, m_awcache, m_awprot, m_awqos} !== 0)
          $fatal(1, "NATIVE unsupported AW addr=%h size=%h len=%h sidebands=%h",
                 m_awaddr, m_awsize, m_awlen, {m_awlock,m_awcache,m_awprot,m_awqos});
        if (m_awready) aw_masks.push_back(32'hf << m_awaddr[4:0]);
      end
      if (m_wvalid === 1'b1 && m_wready === 1'b1) begin
        if (m_wlast !== 1) $fatal(1, "NATIVE multi-beat W not supported");
        w_masks.push_back(m_wstrb);
      end
      while (aw_masks.size()>0 && w_masks.size()>0) begin
        expected_mask = aw_masks.pop_front();
        actual_mask = w_masks.pop_front();
        if (actual_mask !== expected_mask)
          $fatal(1, "NATIVE incorrect byte lanes WSTRB=%h expected=%h", actual_mask, expected_mask);
      end
      if (m_rvalid === 1'b1 &&
          (hbm_rid !== 0 || m_rresp !== 0 || m_rlast !== 1))
        $fatal(1, "HBM read response error ID=%h RESP=%h LAST=%b", hbm_rid, m_rresp, m_rlast);
      if (m_bvalid === 1'b1 && (hbm_bid !== 0 || m_bresp !== 0))
        $fatal(1, "HBM write response error ID=%h RESP=%h", hbm_bid, m_bresp);
    end
    if (!resetn || !measure) begin
      n_ar <= 0; n_r <= 0; n_aw <= 0; n_w <= 0; n_b <= 0;
    end else begin
      if (m_arvalid && m_arready) n_ar <= n_ar+1;
      if (m_rvalid && m_rready) n_r <= n_r+1;
      if (m_awvalid && m_awready) n_aw <= n_aw+1;
      if (m_wvalid && m_wready) n_w <= n_w+1;
      if (m_bvalid && m_bready) n_b <= n_b+1;
      if (n_ar>16 || n_r>16 || n_aw>8 || n_w>8 || n_b>8)
        $fatal(1, "Extra native traffic");
    end
  end

  always @(posedge kernel_clk)
    if (measure && (ld_awvalid || ld_wvalid || ld_arvalid || ld_bready || ld_rready))
      $fatal(1, "Loader active during measurement");
"""

TB_RUN = r"""
  initial begin
    $timeformat(-9, 3, " ns", 0);
    wait (ready_kernel === 1'b1);
    repeat (16) @(posedge kernel_clk);
    $display("HBM_READY time=%t kernel_period_ps=10000 memory_period_ps=2222", $time);
    for (run_number=1; run_number<=2; run_number=run_number+1) begin
      initialize_memory();
      check_memory(0);
      repeat (16) @(posedge kernel_clk);
      @(negedge kernel_clk);
      if (idle !== 1 || done !== 0)
        $fatal(1, "DUT not ready before launch run=%0d idle=%b done=%b", run_number, idle, done);
      measure = 1; start = 1;
      @(posedge kernel_clk); start_time = $time;
      @(negedge kernel_clk); start = 0;
      do begin
        @(posedge kernel_clk); #1;
        if ($isunknown(done)) $fatal(1, "Unknown DUT done signal");
      end while (done !== 1'b1);
      done_time = $time-1;
      while (!drained()) begin @(posedge kernel_clk); #1; end
      drain_time = $time-1;
      $display("RESULT_JSON {\"run\":%0d,\"kernel_period_ps\":10000,\"memory_period_ps\":2222,\"start_done_cycles\":%0d,\"start_drain_cycles\":%0d,\"dut_reads\":%0d,\"dut_writes\":%0d,\"hbm_reads\":%0d,\"hbm_writes\":%0d}",
               run_number, (done_time-start_time)/10000, (drain_time-start_time)/10000,
               rd_req[0]+rd_req[1]+rd_req[2], wr_req[0]+wr_req[1]+wr_req[2], n_ar, n_aw);
      @(negedge kernel_clk); measure = 0;
      // This drains and verifies through the loader without resetting HBM/bridge.
      check_memory(1);
      repeat (16) @(posedge kernel_clk);
    end
    $display("HBM_BAMBU_TEST_PASSED");
    $finish;
  end
  initial begin
    #900000000;
    $fatal(1, "HBM_BAMBU_TEST_FAILED watchdog run=%0d ready=%b measure=%b done=%b native_AR/R/AW/W/B=%0d/%0d/%0d/%0d/%0d DUT_A_AR/R=%0d/%0d DUT_B_AR/R=%0d/%0d DUT_C_AW/W/B=%0d/%0d/%0d",
           run_number, ready_kernel, measure, done, n_ar, n_r, n_aw, n_w, n_b,
           rd_req[0], rd_rsp[0], rd_req[1], rd_rsp[1], wr_req[2], wr_data[2], wr_rsp[2]);
  end
"""


def prepare():
    snapshot = BASELINE / "config_snapshot/smoke_axi_1ch"
    metadata = json.loads((snapshot / "inputs.json").read_text())
    input_paths = [snapshot / "inputs" / name for name in metadata["inputs_sha256"]]
    for name, expected_hash in metadata["inputs_sha256"].items():
        path = snapshot / "inputs" / name
        if sha(path) != expected_hash:
            raise ValueError("Baseline input hash mismatch: " + str(path))
    yaml = snapshot / "hbm2_32ch.yaml"
    if sha(yaml) != metadata["yaml_sha256"]:
        raise ValueError("Baseline YAML hash mismatch")
    if metadata["clock_period_ns"] != "10":
        raise ValueError("Expected the saved 10 ns baseline")
    xml = snapshot / "inputs/smoke/test_vector_add.xml"
    cases = ET.parse(xml).getroot().findall("testbench")
    if len(cases) != 1 or cases[0].attrib["n"] != "8":
        raise ValueError("Expected one n=8 test case")
    vectors = []
    for name in ("vec_a", "vec_b", "vec_c"):
        raw = cases[0].attrib[name].strip()
        if not (raw.startswith("{") and raw.endswith("}")):
            raise ValueError("Unsupported input vector: " + raw)
        values = [int(item.strip(), 0) for item in raw[1:-1].split(",")]
        if len(values) != 8:
            raise ValueError("Expected 8 elements for " + name)
        vectors.append(values)
    for x, y in zip(vectors[0], vectors[1]):
        if not (-2**31 <= x <= 2**31-1 and -2**31 <= y <= 2**31-1 and
                -2**31 <= x+y <= 2**31-1):
            raise ValueError("Signed C addition would overflow")
    rtl = BASELINE / "work/smoke_axi_1ch/output"
    wrapper = ROOT / "bridge-project/smoke_bridge.gen/sources_1/bd/smoke_bridge/hdl/smoke_bridge_wrapper.v"
    dut_ports, bridge_ports = expected_ports()
    check_ports(rtl / "vector_add.v", "vector_add", dut_ports)
    check_ports(wrapper, "smoke_bridge_wrapper", bridge_ports)
    required = [
        ROOT / "bridge-project/smoke_bridge.xpr",
        ROOT / "example/hbm_reference_ex/hbm_reference_ex.xpr",
        ROOT / "simlibs-vivado2024.2-vcs2025.06sp2/synopsys_sim.setup",
        ROOT / "example/hbm_reference_ex/imports/example_top_sim.sv",
    ]
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)
    run = ROOT / "integration-runs" / datetime.datetime.now().strftime("run_%Y%m%d_%H%M%S_%f")
    run.mkdir(parents=True, exist_ok=False)
    (run / "rtl").mkdir()
    (run / "inputs").mkdir()
    for name in ("vector_add.v", "panda_libtech.v"):
        shutil.copy2(rtl / name, run / "rtl" / name)
    for path in input_paths + [snapshot / "inputs.json", yaml]:
        shutil.copy2(path, run / "inputs" / path.name)
    (run / "tb_hbm_bambu.sv").write_text(testbench(*vectors))
    (run / "simulate.do").write_text("run 1ms\nquit\n")
    tracked = input_paths + [snapshot / "inputs.json", yaml, wrapper,
                              rtl / "vector_add.v", rtl / "panda_libtech.v"] + required
    tracked += list((ROOT / "example/hbm_reference_ex").rglob("hbm_reference.xci"))
    tracked += list((ROOT / "bridge-project/smoke_bridge.srcs").rglob("smoke_bridge.bd"))
    manifest = {
        "baseline": str(BASELINE), "baseline_reported_cycles": 84,
        "kernel_period_ps": 10000, "hbm_axi_period_ps": 2222,
        "addresses": {"vec_" + name: hex(addr) for name, addr in zip("abc", BASES)},
        "vectors": dict(zip(("vec_a", "vec_b", "vec_c"), vectors)), "n": 8,
        "rounds": 2,
        "adaptation": "single-beat 32-bit word to aligned 32-byte HBM beat; preserve WSTRB; no cache",
        "measurement": "launch edge to sampled done; separately launch to all AXI responses drained",
        "preconditioning": "AXI initialization and full readback of vectors and guard lines before each launch",
        "performance_comparison_aligned": False,
        "source_sha256": {str(path): sha(path) for path in tracked},
        "tb_sha256": sha(run / "tb_hbm_bambu.sv"),
        "generator_sha256": sha(__file__),
        "sources": [
            "https://docs.amd.com/r/en-US/pg276-axi-hbm/AXI-Considerations",
            "https://www.xilinx.com/support/documents/ip_documentation/smartconnect/v1_0/pg247-smartconnect.pdf",
        ],
    }
    (run / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (ROOT / "integration-last-prepared.txt").write_text(str(run) + "\n")
    print("PREPARED:", run)
    print("PORT_CONTRACT_OK: vector_add and smoke_bridge_wrapper")
    print("INPUT_HASHES_OK")
    print("EXPECTED:", [x+y for x, y in zip(*vectors[:2])])
    print("Next: export_integration.tcl with HBM_INTEGRATION_DIR set to this directory.")


def locate_script(run, export_name):
    scripts = list((run / export_name / "vcs").glob("*.sh"))
    if len(scripts) != 1:
        raise ValueError("Expected one VCS script in %s, found %s" % (export_name, scripts))
    expected = {"export-hbm": "sim_tb_top.sh", "export-bridge": "smoke_bridge_wrapper.sh"}[export_name]
    if scripts[0].name != expected:
        raise ValueError("Invalid %s top: expected %s, found %s" %
                         (export_name, expected, scripts[0].name))
    return scripts[0]


def verify_export(run):
    log = (run / "export.log").read_text(errors="replace")
    errors = re.findall(r"(?m)^\s*ERROR:.*$", log)
    if errors:
        raise ValueError("Vivado export contains errors:\n" + "\n".join(errors))
    required = {
        "export-bridge": ("smoke_bridge_wrapper.v",),
        "export-hbm": ("hbm_reference.v", "hbm_model.sv"),
    }
    for export_name, sources in required.items():
        script = locate_script(run, export_name)
        content = script.read_text()
        for source in sources:
            if source not in content:
                raise ValueError("Export script %s is missing source %s" % (script, source))
    print("INTEGRATION_EXPORT_OK:", run)


def preserve_libraries(script):
    # Operate on a private copy of the generated script, never on the original.
    # Both exports compile into the same physical libraries. Removing vcs_lib
    # between the two invocations would discard the first export.
    source = script.read_text()
    pattern = r'(?m)^  if \[\[ -e \$sim_lib_dir \]\]; then\n    rm -rf \$sim_lib_dir\n  fi\n'
    source, count = re.subn(pattern, "  # Preserve shared physical libraries in this fresh run.\n", source)
    if count != 1:
        raise ValueError("Unexpected create_lib_dir implementation in " + str(script))
    match = re.search(r"(?m)^design_libs=\(([^)]*)\)", source)
    if not match:
        raise ValueError("Missing design_libs in " + str(script))
    libraries = shlex.split(match.group(1))
    if any(not re.fullmatch(r"[A-Za-z0-9_]+", name) for name in libraries):
        raise ValueError("Unexpected library names")
    return source, libraries


def command(args, cwd):
    print("+", shlex.join([str(arg) for arg in args]), flush=True)
    subprocess.run([str(arg) for arg in args], cwd=cwd, check=True)


def plan_export_data(scripts):
    """Check all runtime-file clashes before creating the compiler workdir."""
    runtime_suffixes = {".mem", ".dat", ".hex", ".coe"}
    runtime_text_names = {"axi_tg.txt"}  # The inspected example's TG pattern.
    by_relative = {}
    metadata_hashes = {}
    for script in scripts:
        for path in sorted(script.parent.rglob("*")):
            if not path.is_file():
                continue
            # Copy by runtime format, not all .txt files. Vivado writes distinct
            # README/inventory text per design. All unselected text stays in the
            # original exports, with hashes recorded for provenance.
            if path.suffix.lower() == ".txt" and path.name not in runtime_text_names:
                metadata_hashes[str(path)] = sha(path)
                continue
            if path.suffix.lower() not in runtime_suffixes and path.name not in runtime_text_names:
                continue
            relative = path.relative_to(script.parent)
            digest = sha(path)
            if relative in by_relative and by_relative[relative][2] != digest:
                raise ValueError("Conflicting export data file: " + str(relative))
            by_relative.setdefault(relative, (path, relative, digest))
    return list(by_relative.values()), metadata_hashes


def compile_testbench(run):
    work = run / "vcs"
    command(["vlogan", "-full64", "-work", "xil_defaultlib", "-sverilog",
             "+incdir+" + str(run / "rtl"), "-l", "kernel-compile.log",
             run / "rtl/panda_libtech.v", run / "rtl/vector_add.v",
             run / "tb_hbm_bambu.sv"], work)
    command(["vcs", "-full64", "-debug_acc", "-t", "ps", "-licqueue",
             "-l", "elaborate.log", "xil_defaultlib.tb_hbm_bambu",
             "xil_defaultlib.glbl", "-o", "tb_hbm_bambu_simv"], work)


def rebuild_testbench(run):
    """Correct this run in place; reuse the already compiled vendor libraries."""
    verify_export(run)
    work = run / "vcs"
    if not (work / "synopsys_sim.setup").is_file():
        raise ValueError("Missing compiled-library mapping; run compile first")
    manifest = json.loads((run / "manifest.json").read_text())
    build = json.loads((run / "build.json").read_text())
    if manifest["n"] != 8:
        raise ValueError("Expected the inspected n=8 case")
    vectors = manifest["vectors"]
    if manifest["addresses"] != {"vec_" + name: hex(addr) for name, addr in zip("abc", BASES)}:
        raise ValueError("Run addresses do not match this testbench")
    # Update the existing source and metadata, without archives or new runs.
    (run / "tb_hbm_bambu.sv").write_text(testbench(
        vectors["vec_a"], vectors["vec_b"], vectors["vec_c"]))
    manifest["tb_sha256"] = sha(run / "tb_hbm_bambu.sv")
    manifest["generator_sha256"] = sha(__file__)
    (run / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    build["testbench_rebuild_complete"] = False
    build["tb_sha256"] = manifest["tb_sha256"]
    (run / "build.json").write_text(json.dumps(build, indent=2) + "\n")
    if (run / "results.json").exists():
        (run / "results.json").unlink()
    compile_testbench(run)
    build["testbench_rebuild_complete"] = True
    (run / "build.json").write_text(json.dumps(build, indent=2) + "\n")
    print("TESTBENCH_REBUILD_OK:", work / "tb_hbm_bambu_simv")


def compile_vendor(run, export_run):
    verify_export(export_run)
    if (run / "vcs").exists():
        raise ValueError("This run already has a vcs directory. Prepare a new run to retry without overwriting evidence.")
    scripts = [locate_script(export_run, name) for name in ("export-hbm", "export-bridge")]
    # Validate both generated formats before starting any compiler.
    patched = [preserve_libraries(script) for script in scripts]
    data_plan, metadata_hashes = plan_export_data(scripts)
    work = run / "vcs"
    work.mkdir()
    # Exported boot/configuration data must be present in the simulator CWD.
    # Preserve the relative paths used by readmemh/readmemb, and reject clashes.
    data_hashes = {}
    for path, relative, digest in data_plan:
        destination = work / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        data_hashes[str(relative)] = digest
    libraries = sorted({name for _, names in patched for name in names})
    for index, (source, _) in enumerate(patched):
        (work / ("compile_export_%d.sh" % index)).write_text(source)
    base_libs = ROOT / "simlibs-vivado2024.2-vcs2025.06sp2"
    for index in range(len(patched)):
        command(["bash", work / ("compile_export_%d.sh" % index),
                 "-step", "compile", "-lib_map_path", base_libs], work)
        if (work / "compile.log").exists():
            shutil.copy2(work / "compile.log", work / ("compile-export-%d.log" % index))
    setup = ["LIBRARY_SCAN=TRUE"]
    setup += ["%s:vcs_lib/%s" % (name, name) for name in libraries]
    setup += ["OTHERS=" + str(base_libs / "synopsys_sim.setup")]
    (work / "synopsys_sim.setup").write_text("\n".join(setup) + "\n")
    return {
        "libraries": libraries,
        "export_data_sha256": data_hashes,
        "export_metadata_sha256": metadata_hashes,
        "export_script_sha256": {str(path): sha(path) for path in scripts},
        "synopsys_sim_setup_sha256": sha(work / "synopsys_sim.setup"),
        "tools": {name: shutil.which(name) for name in ("vlogan", "vcs", "vhdlan")},
    }


def compile_run(run):
    build = compile_vendor(run, run)
    compile_testbench(run)
    build.update(tb_sha256=sha(run / "tb_hbm_bambu.sv"), testbench_rebuild_complete=True)
    (run / "build.json").write_text(json.dumps(build, indent=2) + "\n")
    print("COMPILE_AND_ELABORATE_OK:", work / "tb_hbm_bambu_simv")


def simulate_run(run):
    work = run / "vcs"
    build = json.loads((run / "build.json").read_text())
    if (build.get("testbench_rebuild_complete") is not True or
            build.get("tb_sha256") != sha(run / "tb_hbm_bambu.sv")):
        raise ValueError("Testbench was changed or rebuild is incomplete; run rebuild-testbench first")
    if (run / "results.json").exists():
        (run / "results.json").unlink()
    # The user requested corrections in place and reuse of the existing run.
    # Clear the previous log so a failed invocation cannot reuse an old PASS.
    (work / "simulate.log").write_text("")
    command([work / "tb_hbm_bambu_simv", "-ucli", "-licqueue",
             "-l", "simulate.log", "-do", run / "simulate.do"], work)
    log = (work / "simulate.log").read_text(errors="replace")
    if "HBM_BAMBU_TEST_PASSED" not in log:
        raise ValueError("Missing final functional PASS marker; simulator exit code alone is insufficient")
    results = [json.loads(match.group(1))
               for match in re.finditer(r"(?m)^RESULT_JSON (\{.*\})\s*$", log)]
    if len(results) != 2 or [item["run"] for item in results] != [1, 2]:
        raise ValueError("Expected results for two launches without reset")
    for item in results:
        if any(item[key] != value for key, value in
               {"dut_reads": 16, "dut_writes": 8, "hbm_reads": 16, "hbm_writes": 8}.items()):
            raise ValueError("Traffic counts do not match the saved smoke case")
        if not (0 < item["start_done_cycles"] <= item["start_drain_cycles"]):
            raise ValueError("Invalid measurement boundaries")
    (run / "results.json").write_text(json.dumps({
        "functional_pass": True, "performance_comparison_aligned": False,
        "results": results, "simulation_log_sha256": sha(work / "simulate.log"),
    }, indent=2) + "\n")
    print("FUNCTIONAL_PASS: both launches, vectors, guard lines and traffic checked")
    print(json.dumps(results, indent=2))
    print("No performance ratio computed: alignment with Ramulator is still required.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify-export", "compile", "rebuild-testbench", "simulate"))
    parser.add_argument("--run", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
    else:
        run = args.run or Path((ROOT / "integration-last-prepared.txt").read_text().strip())
        run = run.resolve(strict=True)
        if run.parent != (ROOT / "integration-runs").resolve():
            raise ValueError("Run must be a direct child of integration-runs")
        if args.action == "verify-export":
            verify_export(run)
        elif args.action == "compile":
            compile_run(run)
        elif args.action == "rebuild-testbench":
            rebuild_testbench(run)
        else:
            simulate_run(run)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print("STOP:", error, file=sys.stderr)
        sys.exit(1)
