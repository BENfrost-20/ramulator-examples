# Export generated sources into the newly prepared run. No save_project,
# regeneration of HBM, or compilation of the base-library catalogue.
if {![string match 2024.2* [version -short]]} {error "Vivado 2024.2 required"}
if {![info exists ::env(HBM_INTEGRATION_DIR)]} {error "Set HBM_INTEGRATION_DIR"}
set root [file normalize [file join $::env(HOME) thesis hbm-reference-smoke]]
set run [file normalize $::env(HBM_INTEGRATION_DIR)]
if {![file exists [file join $run manifest.json]]} {error "Run prepare_integration.py prepare first"}
if {[file dirname $run] ne [file join $root integration-runs]} {error "Unexpected run directory"}
set libraries [file join $root simlibs-vivado2024.2-vcs2025.06sp2]
if {![file exists [file join $libraries synopsys_sim.setup]]} {error "Missing base-library mapping"}
foreach output {export-hbm export-bridge} {
    if {[file exists [file join $run $output]]} {error "Refusing to overwrite $output; prepare a fresh run"}
}

open_project [file join $root bridge-project smoke_bridge.xpr]
set wrapper [file join $root bridge-project smoke_bridge.gen sources_1 bd smoke_bridge hdl smoke_bridge_wrapper.v]
if {![file exists $wrapper]} {error "Missing generated bridge wrapper"}
if {[llength [get_files -quiet $wrapper]] == 0} {
    add_files -norecurse $wrapper
}
set_property top smoke_bridge_wrapper [get_filesets sim_1]
update_compile_order -fileset sim_1
if {[get_property top [get_filesets sim_1]] ne "smoke_bridge_wrapper"} {
    error "Bridge simulation top was not set"
}
export_simulation -simulator vcs -directory [file join $run export-bridge] -lib_map_path $libraries -absolute_path
if {![file exists [file join $run export-bridge vcs smoke_bridge_wrapper.sh]]} {
    error "Expected bridge VCS script was not generated"
}
close_project

open_project [file join $root example hbm_reference_ex hbm_reference_ex.xpr]
set_property top sim_tb_top [get_filesets sim_1]
update_compile_order -fileset sim_1
export_simulation -simulator vcs -directory [file join $run export-hbm] -lib_map_path $libraries -absolute_path
if {![file exists [file join $run export-hbm vcs sim_tb_top.sh]]} {
    error "Expected HBM VCS script was not generated"
}
close_project
puts "INTEGRATION_EXPORT_GENERATED: $run"
