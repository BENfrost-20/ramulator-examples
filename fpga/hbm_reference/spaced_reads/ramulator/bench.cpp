#include "Vfpga_kernel.h"
#include "verilated.h"

#include "abi.hpp"
#include "functional_axi.hpp"
static constexpr unsigned case_banks=1, slab_bytes=65536;
#include <iostream>
static std::uint64_t cycles=0;
Vfpga_kernel dut;std::vector<Bytes> memory(case_banks,Bytes(slab_bytes,0xa5));
std::uint64_t base(unsigned b){return 0x1200000000ULL+(std::uint64_t(b)<<24);}
Port ports[] = {{&memory[0],base(0)}};
void step(){if(cycles>20000000)throw std::runtime_error("Simulation watchdog");dut.ap_clk=0;
#ifdef FPGA_WITH_RAMULATOR
if(cycles) timing->advance_cycle();
#endif
ports[0].update(cycles);
 dut.m_axi_0_arready=ports[0].arready(cycles);
 dut.m_axi_0_awready=ports[0].awready(cycles);
 dut.m_axi_0_wready=ports[0].wready(cycles);
 dut.m_axi_0_rvalid=ports[0].rv;dut.m_axi_0_rid=ports[0].rid;dut.m_axi_0_rdata=ports[0].rd;
 dut.m_axi_0_rlast=1;dut.m_axi_0_rresp=0;
 dut.m_axi_0_bvalid=ports[0].bv;dut.m_axi_0_bid=ports[0].bid;dut.m_axi_0_bresp=0;
dut.eval();
if(dut.ap_rst_n) {
 if(dut.m_axi_0_rvalid&&dut.m_axi_0_rready)ports[0].consume_read(cycles);
 if(dut.m_axi_0_bvalid&&dut.m_axi_0_bready)ports[0].consume_write(cycles);
 if(dut.m_axi_0_arvalid&&dut.m_axi_0_arready)ports[0].ar(dut.m_axi_0_araddr,dut.m_axi_0_arid,dut.m_axi_0_arsize,dut.m_axi_0_arlen,cycles);
 if(dut.m_axi_0_awvalid&&dut.m_axi_0_awready)ports[0].write_addr(dut.m_axi_0_awaddr,dut.m_axi_0_awid,dut.m_axi_0_awsize,dut.m_axi_0_awlen,cycles);
 if(dut.m_axi_0_wvalid&&dut.m_axi_0_wready)ports[0].write_data(dut.m_axi_0_wdata,dut.m_axi_0_wstrb,dut.m_axi_0_wlast,cycles);
 }

 dut.ap_clk=1;dut.eval();++cycles;
}
void write(unsigned a,unsigned v,unsigned strobe=15,bool reverse=false){
 dut.s_axi_control_bready=0;bool adone=false,wdone=false;
 for(unsigned i=0;!adone||!wdone;++i){
  dut.ap_clk=0;dut.s_axi_control_awaddr=a;dut.s_axi_control_wdata=v;dut.s_axi_control_wstrb=strobe;
  dut.s_axi_control_awvalid=!adone&&(reverse?i>=3:true);
  dut.s_axi_control_wvalid=!wdone&&(reverse?true:i>=3);dut.eval();
  bool ah=dut.s_axi_control_awvalid&&dut.s_axi_control_awready;
  bool wh=dut.s_axi_control_wvalid&&dut.s_axi_control_wready;step();adone|=ah;wdone|=wh;
 }
 dut.s_axi_control_awvalid=0;dut.s_axi_control_wvalid=0;
 while(!dut.s_axi_control_bvalid)step();
 auto resp=dut.s_axi_control_bresp;
 // Response must remain stable under backpressure.
 for(unsigned i=0;i<3;++i){step();if(!dut.s_axi_control_bvalid||dut.s_axi_control_bresp!=resp)throw std::runtime_error("Unstable B response");}
 dut.s_axi_control_bready=1;step();dut.s_axi_control_bready=0;
 if(resp)throw std::runtime_error("AXI-Lite write rejected");
}
unsigned read(unsigned a){
 dut.s_axi_control_araddr=a;dut.s_axi_control_arvalid=1;dut.s_axi_control_rready=0;
 dut.ap_clk=0;dut.eval();while(!dut.s_axi_control_arready)step();step();dut.s_axi_control_arvalid=0;
 while(!dut.s_axi_control_rvalid)step();auto v=dut.s_axi_control_rdata;
 if(dut.s_axi_control_rresp)throw std::runtime_error("AXI-Lite read rejected");
 for(unsigned i=0;i<2;++i){step();if(!dut.s_axi_control_rvalid||dut.s_axi_control_rdata!=v)throw std::runtime_error("Unstable R response");}
 dut.s_axi_control_rready=1;step();dut.s_axi_control_rready=0;return v;
}

int main(int argc, char** argv) try {
  Verilated::commandArgs(argc,argv);
  if (argc!=3) throw std::runtime_error("Pass YAML and warmup cycles");
  auto warmup=std::stoul(argv[2]);
  if (warmup>=390) throw std::runtime_error("Warmup outside 0–389 cycles");
  timing=std::make_unique<RamulatorTiming>(argv[1], 10);
  std::cout << "DRAM ticks per 100 MHz kernel cycle: " << timing->ratio() << '\n';
  model_data_base=0x40000000ULL;
  trace_n=1000;
  axi_trace.open("ramulator-axi.jsonl");
  if (!axi_trace) throw std::runtime_error("Cannot open AXI trace");
  auto& bytes=memory[0];
  bytes[256]=0x78;bytes[257]=0x56;bytes[258]=0x34;bytes[259]=0x12;
  dut.s_axi_control_awvalid=0;dut.s_axi_control_wvalid=0;
  dut.s_axi_control_arvalid=0;dut.s_axi_control_bready=0;dut.s_axi_control_rready=0;
  dut.ap_rst_n=0;for (unsigned i=0;i<8;++i) step();dut.ap_rst_n=1;step();
  if (read(0x90)!=0x52444631 || read(0)!=0) throw std::runtime_error("Wrong RTL or reset state");
  auto address=base(0)+256;
  write(0x20,unsigned(address));write(0x24,unsigned(address>>32));
  if (read(0x20)!=unsigned(address) || read(0x24)!=unsigned(address>>32))
    throw std::runtime_error("BO address readback mismatch");
  for(unsigned i=0;i<warmup;++i) step();
  write(0,1);
  while (!(read(0)&abi::DRAINED)) step();
  if ((read(0)&(abi::BUSY|abi::ERROR)) || read(4)!=1 ||
      ports[0].reads!=1000 || ports[0].writes || !ports[0].empty())
    throw std::runtime_error("Probe status or traffic check failed");
  std::ofstream out("latencies.csv");
  if (!out) throw std::runtime_error("Cannot open latency CSV");
  out << "sample,ar_cycle,rvalid_cycle,r_cycle,latency_cycles\n";
  unsigned previous=0;
  for(unsigned i=0;i<1000;++i) {
    write(0x10,i);
    auto ar=read(0x94), r=read(0x98);
    if (r<=ar || ar<previous+50) throw std::runtime_error("Invalid sample timing");
    out<<i+1<<','<<ar<<','<<r<<','<<r<<','<<r-ar<<'\n';
    previous=r;
  }
  out.close();
  if (!out) throw std::runtime_error("Incomplete latency CSV");
  timing.reset();
  std::cout<<"PASS 1000 AXI reads with Ramulator, warmup="<<warmup<<"\n";
  return 0;
} catch (const std::exception& e) {
  std::cerr<<e.what()<<'\n'; return 1;
}
