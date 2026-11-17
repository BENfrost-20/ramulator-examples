open_project ./example/hbm_reference_ex/hbm_reference_ex.xpr
set_property target_simulator VCS [current_project]
set_property simulator.vcs_install_dir /opt/synopsys/vcs/X-2025.06-SP2/bin [current_project]

puts "SIMSET: [current_fileset -simset]"
puts "TOP: [get_property TOP [current_fileset -simset]]"

export_simulation -simulator vcs \
  -directory ./export-example-vcs \
  -absolute_path -force

close_project
