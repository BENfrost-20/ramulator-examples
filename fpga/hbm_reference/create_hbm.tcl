create_project hbm_reference ./project -part xcu55c-fsvh2892-2L-e
create_ip -name hbm -vendor xilinx.com -library ip \
  -version 1.0 -module_name hbm_reference

set ip [get_ips hbm_reference]
set report [open hbm-properties.txt w]
foreach property [lsort [list_property $ip]] {
  if {[string match CONFIG.* $property]} {
    puts $report "$property = [get_property $property $ip]"
  }
}
close $report
close_project
