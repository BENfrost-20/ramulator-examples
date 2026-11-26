set reg [ipx::add_register COMMAND $ab]
set_property address_offset 0 $reg
set_property size 32 $reg
set reg [ipx::add_register GENERATION $ab]
set_property address_offset 4 $reg
set_property size 32 $reg
set reg [ipx::add_register N $ab]
set_property address_offset 16 $reg
set_property size 32 $reg
set reg [ipx::add_register CORE_CYCLES $ab]
set_property address_offset 128 $reg
set_property size 64 $reg
set reg [ipx::add_register DRAIN_CYCLES $ab]
set_property address_offset 136 $reg
set_property size 64 $reg
set reg [ipx::add_register base0 $ab]
set_property address_offset 32 $reg
set_property size 64 $reg
ipx::add_register_parameter ASSOCIATED_BUSIF $reg
set_property value {m_axi_0} [ipx::get_register_parameters ASSOCIATED_BUSIF -of_objects $reg]
set reg [ipx::add_register TRACE_ID $ab]
set_property address_offset 144 $reg
set_property size 32 $reg
set reg [ipx::add_register AR_TICK $ab]
set_property address_offset 148 $reg
set_property size 32 $reg
set reg [ipx::add_register R_TICK $ab]
set_property address_offset 152 $reg
set_property size 32 $reg
