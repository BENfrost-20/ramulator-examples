# Update the already generated project; preserve the DUT and the HBM example.
# Inspected MinimalAXI4AdapterSingleBeat drives AW/AR/WUSER to zero and does
# not consume R/BUSER. The final testbench must assert those constants and
# tie DUT response USER bits to zero. No DUT port or RTL is changed here.
if {![string match 2024.2* [version -short]]} {error "Vivado 2024.2 required"}
set out [file normalize [file join $::env(HOME) thesis hbm-reference-smoke bridge-project]]
open_project [file join $out smoke_bridge.xpr]
set bd [get_files */smoke_bridge.bd]
open_bd_design $bd
foreach name {S_A S_B S_C S_LOAD} {
    set_property -dict [list CONFIG.AWUSER_WIDTH 0 CONFIG.ARUSER_WIDTH 0 \
        CONFIG.WUSER_WIDTH 0 CONFIG.RUSER_WIDTH 0 CONFIG.BUSER_WIDTH 0] \
        [get_bd_intf_ports $name]
}
set_property CONFIG.ASSOCIATED_BUSIF {S_A:S_B:S_C:S_LOAD} [get_bd_ports kernel_clk]
set_property CONFIG.ASSOCIATED_BUSIF M_HBM [get_bd_ports memory_clk]
validate_bd_design
save_bd_design
set report [open [file join $out interface-properties.txt] w]
foreach p [get_bd_intf_pins -of_objects [get_bd_cells sc]] {
    puts $report "INTERFACE $p"
    foreach property [lsort [list_property $p]] {
        if {[string match CONFIG.* $property]} {
            puts $report "$property = [get_property $property $p]"
        }
    }
}
close $report
generate_target all $bd
set wrapper [make_wrapper -files $bd -top]
puts "BRIDGE_WRAPPER: $wrapper"
puts "BRIDGE_PROPERTIES: [file join $out interface-properties.txt]"
close_project
