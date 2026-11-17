# Smoke vector_add integration stage: vendor interconnect only.
# Run with Vivado 2024.2. Does not modify either baseline or HBM example.
if {![string match 2024.2* [version -short]]} {error "Vivado 2024.2 required"}
set out [file normalize [file join $::env(HOME) thesis hbm-reference-smoke bridge-project]]
if {[file exists $out]} {error "Refusing to overwrite existing bridge project: $out"}
create_project smoke_bridge $out -part xcu55c-fsvh2892-2L-e
create_bd_design smoke_bridge

set kclk [create_bd_port -dir I -type clk kernel_clk]
set mclk [create_bd_port -dir I -type clk memory_clk]
set rst [create_bd_port -dir I -type rst resetn]
set_property CONFIG.FREQ_HZ 100000000 $kclk
set_property CONFIG.FREQ_HZ 450000000 $mclk
set_property CONFIG.POLARITY ACTIVE_LOW $rst
set_property CONFIG.ASSOCIATED_BUSIF {S_A:S_B:S_C:S_LOAD} $kclk
set_property CONFIG.ASSOCIATED_RESET resetn $kclk
set_property CONFIG.ASSOCIATED_BUSIF M_HBM $mclk
set_property CONFIG.ASSOCIATED_RESET resetn $mclk

set sc [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 sc]
set_property -dict [list CONFIG.NUM_SI 4 CONFIG.NUM_MI 1 CONFIG.NUM_CLKS 2] $sc
connect_bd_net $kclk [get_bd_pins sc/aclk]
connect_bd_net $mclk [get_bd_pins sc/aclk1]
connect_bd_net $rst [get_bd_pins sc/aresetn]

set index 0
foreach name {S_A S_B S_C S_LOAD} {
    set port [create_bd_intf_port -mode Slave -vlnv xilinx.com:interface:aximm_rtl:1.0 $name]
    set_property -dict [list CONFIG.PROTOCOL AXI4 CONFIG.ADDR_WIDTH 64 \
        CONFIG.DATA_WIDTH 32 CONFIG.ID_WIDTH 6 CONFIG.FREQ_HZ 100000000 \
        CONFIG.HAS_BURST 1 CONFIG.HAS_LOCK 1 CONFIG.HAS_CACHE 1 CONFIG.HAS_PROT 1 \
        CONFIG.HAS_QOS 1 CONFIG.HAS_REGION 1 CONFIG.SUPPORTS_NARROW_BURST 1 \
        CONFIG.AWUSER_WIDTH 0 CONFIG.ARUSER_WIDTH 0 CONFIG.WUSER_WIDTH 0 \
        CONFIG.RUSER_WIDTH 0 CONFIG.BUSER_WIDTH 0] $port
    connect_bd_intf_net $port [get_bd_intf_pins [format sc/S%02d_AXI $index]]
    incr index
}
set port [create_bd_intf_port -mode Master -vlnv xilinx.com:interface:aximm_rtl:1.0 M_HBM]
set_property -dict [list CONFIG.PROTOCOL AXI3 CONFIG.ADDR_WIDTH 34 \
    CONFIG.DATA_WIDTH 256 CONFIG.FREQ_HZ 450000000 \
    CONFIG.HAS_BURST 1 CONFIG.HAS_LOCK 0 \
    CONFIG.HAS_CACHE 0 CONFIG.HAS_PROT 0 CONFIG.HAS_QOS 0 CONFIG.HAS_REGION 0] $port
connect_bd_intf_net [get_bd_intf_pins sc/M00_AXI] $port

# Explicit 8 GiB aperture for this generated one-stack reference configuration.
# No remapping: upper-address and nonzero unsupported-sideband guards belong
# in the testbench before the bridge. Do not truncate DUT IDs manually.
set target [get_bd_addr_segs -quiet M_HBM/Reg]
if {[llength $target] != 1} {
    puts "ADDRESS_SEGMENTS: [get_bd_addr_segs]"
    error "Expected external M_HBM/Reg address segment; inspect generated metadata"
}
foreach name {S_A S_B S_C S_LOAD} {
    assign_bd_address -target_address_space [get_bd_addr_spaces $name] \
        -offset 0x0000000000000000 -range 8G $target
}
validate_bd_design
save_bd_design
set report [open [file join $out interface-properties.txt] w]
foreach p [get_bd_intf_pins -of_objects $sc] {
    puts $report "INTERFACE $p"
    foreach property [lsort [list_property $p]] {
        if {[string match CONFIG.* $property]} {
            puts $report "$property = [get_property $property $p]"
        }
    }
}
close $report
set bd [get_files */smoke_bridge.bd]
generate_target all $bd
set wrapper [make_wrapper -files $bd -top]
add_files $wrapper
set_property top smoke_bridge_wrapper [current_fileset]
puts "BRIDGE_WRAPPER: $wrapper"
puts "BRIDGE_PROPERTIES: [file join $out interface-properties.txt]"
close_project
