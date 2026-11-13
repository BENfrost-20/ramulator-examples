// Compiled only after preparation, against installed XRT; never part of snapshots.
#include <xrt/xrt_device.h>
#include <xrt/xrt_bo.h>
#if __has_include(<xrt/experimental/xrt_ip.h>)
#include <xrt/experimental/xrt_ip.h>
#include <xrt/experimental/xrt_xclbin.h>
#else
#include <experimental/xrt_ip.h>
#include <experimental/xrt_xclbin.h>
#endif
#include "abi.hpp"
#include "case.hpp"
#include "buffers.hpp"
#include <chrono>
#include <fstream>
#include <iostream>
#include <memory>
#include <string>
#include <thread>

// Keep BOs alive even if register I/O throws while a kernel might still DMA.
// Declared after the BO container, so this guard runs before BO destructors.
struct InFlightGuard {
 bool active=false;
 ~InFlightGuard() {
  if(active) {
   std::cerr<<"Host error while accelerator may still run. BOs remain pinned. Recover/reset the device before terminating this process.\n";
   for(;;)std::this_thread::sleep_for(std::chrono::seconds(1));
  }
 }
};

int main(int argc,char** argv) {
 try {
  if(argc<3 || argc>7) throw std::runtime_error("Usage: host XCLBIN DEVICE [N [REPETITIONS [TIMEOUT_SECONDS [RESULT.jsonl]]]]");
  unsigned n=argc>3?std::stoul(argv[3]):case_n;
  unsigned reps=argc>4?std::stoul(argv[4]):2;
  double timeout=argc>5?std::stod(argv[5]):60;
  if(!reps || reps>10000 || !(timeout>0) || timeout>86400) throw std::runtime_error("Invalid repetitions/timeout");
  validate_n(n);
  xrt::device device{std::string(argv[2])};
  xrt::xclbin image{std::string(argv[1])};
  // Programming/loading is deliberate: this host is never invoked by build scripts.
  auto program_begin=std::chrono::steady_clock::now();
  auto uuid=device.load_xclbin(image);
  auto program_seconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-program_begin).count();
  xrt::ip ip(device,uuid,"fpga_kernel:{fpga_kernel_1}");
  auto ips=image.get_ips("fpga_kernel:{fpga_kernel_1}");
  if(ips.size()!=1) throw std::runtime_error("Expected one fpga_kernel compute unit");
  auto args=ips[0].get_args();
  if(ip.read_register(abi::COMMAND)&abi::BUSY) throw std::runtime_error("Compute unit already busy; recover before allocation reuse");
  std::vector<std::unique_ptr<xrt::bo>> bos;
  InFlightGuard in_flight;
  std::vector<int> topology(case_banks,-1);
  for(unsigned port=0;port<case_ports;++port) {
   unsigned b=base_register_bank[port];
   auto name="base"+std::to_string(port);
   auto arg=std::find_if(args.begin(),args.end(),[&](const auto& a){return a.get_name()==name;});
   if(arg==args.end()) throw std::runtime_error("Missing xclbin connectivity argument "+name);
   auto mems=arg->get_mems();
   if(mems.size()!=1 || !mems[0].get_used()) throw std::runtime_error("Ambiguous or missing physical memory for "+name);
   // Topology index is obtained from xclbin metadata, never from HBM[n]/DDR[n].
   int index=mems[0].get_index();
   if(topology[b]>=0 && topology[b]!=index) throw std::runtime_error("Aliased pointers require the same connected physical memory");
   topology[b]=index;
  }
  for(unsigned b=0;b<case_banks;++b) {
   if(topology[b]<0) throw std::runtime_error("Missing connected bank");
   bos.emplace_back(new xrt::bo(device,slab_bytes,xrt::bo::flags::normal,topology[b]));
  }
  for(unsigned port=0;port<case_ports;++port) {
   auto addr=bos[base_register_bank[port]]->address()+abi::GUARD;
   ip.write_register(abi::BASE0+8*port,std::uint32_t(addr));
   ip.write_register(abi::BASE0+8*port+4,std::uint32_t(addr>>32));
  }
  std::filesystem::path result_path=argc>6?argv[6]:"board-results.jsonl";
  auto result_directory=result_path.parent_path().empty()?std::filesystem::path("."):result_path.parent_path();
  std::ofstream file(result_path,std::ios::app);
  if(!file) throw std::runtime_error("Cannot open result file");
  if(ip.read_register(abi::COMMAND)&abi::BUSY) throw std::runtime_error("Compute unit already busy; recover before allocation reuse");
  for(unsigned rep=0;rep<reps;++rep) {
   auto initial=case_input(n,rep); auto expected=case_expected(initial,n);
   auto input_file=save_input(initial,n,rep,result_directory);
   auto buffers=pack(initial,case_banks);
   auto expected_banks=pack(expected,case_banks);
   auto input_begin=std::chrono::steady_clock::now();
   for(unsigned b=0;b<case_banks;++b) {
    if(buffers[b].size()+2*abi::GUARD>slab_bytes) throw std::runtime_error("Buffer exceeds guarded allocation");
    Bytes contents(slab_bytes,0xa5);
    std::copy(buffers[b].begin(),buffers[b].end(),contents.begin()+abi::GUARD);
    bos[b]->write(contents.data(),contents.size());bos[b]->sync(XCL_BO_SYNC_BO_TO_DEVICE);
   }
   auto input_dma_seconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-input_begin).count();
   auto previous=ip.read_register(abi::GENERATION);
   ip.write_register(abi::N,n);in_flight.active=true;ip.write_register(abi::COMMAND,1);
   auto begin=std::chrono::steady_clock::now();std::uint32_t status=0;
   while(true) {
    status=ip.read_register(abi::COMMAND);
    auto generation=ip.read_register(abi::GENERATION);
    if(generation==previous+1 && (status&abi::DRAINED) && !(status&abi::BUSY)) break;
    if(std::chrono::duration<double>(std::chrono::steady_clock::now()-begin).count()>timeout) {
     // A host timeout does not stop the FPGA. Keep BOs alive until operator recovery.
     std::cerr<<"TIMEOUT: accelerator may still DMA. BOs remain pinned in this process. "
              <<"Recover/reset the device with your administrator, then terminate this process. Do not reuse the device.\n";
     file<<"{\"mode\":\"physical_board\",\"functional_status\":\"timeout\",\"case\":\""<<case_name<<"\"}\n";file.flush();
     for(;;) std::this_thread::sleep_for(std::chrono::seconds(1));
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
   }
   in_flight.active=false;
   auto poll_seconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-begin).count();
   auto output_begin=std::chrono::steady_clock::now();
   auto read64=[&](unsigned off){return std::uint64_t(ip.read_register(off))|(std::uint64_t(ip.read_register(off+4))<<32);};
   auto core=read64(abi::CORE_CYCLES),drain=read64(abi::DRAIN_CYCLES);
   if(status&abi::ERROR) throw std::runtime_error("AXI response error");
   for(unsigned b=0;b<case_banks;++b) {
    bos[b]->sync(XCL_BO_SYNC_BO_FROM_DEVICE);Bytes got(slab_bytes);bos[b]->read(got.data(),got.size());
    for(std::size_t i=0;i<got.size();++i) {
     auto want=(i>=abi::GUARD && i<abi::GUARD+expected_banks[b].size())?expected_banks[b][i-abi::GUARD]:0xa5;
     if(got[i]!=want) throw std::runtime_error("Oracle/guard mismatch bank "+std::to_string(b)+" byte "+std::to_string(i));
    }
   }
   file<<"{\"mode\":\""<<(std::getenv("XCL_EMULATION_MODE")?"hw_emu":"physical_board")
       <<"\",\"case\":\""<<case_name<<"\",\"functional_status\":\"pass\",\"n\":"<<n
       <<",\"repetition\":"<<rep<<",\"core_cycles\":"<<core<<",\"drain_cycles\":"<<drain
       <<",\"input_file\":\""<<input_file<<"\",\"program_seconds\":"<<program_seconds
       <<",\"input_dma_seconds\":"<<input_dma_seconds<<",\"poll_wall_seconds\":"<<poll_seconds
       <<",\"output_dma_and_check_seconds\":"<<std::chrono::duration<double>(std::chrono::steady_clock::now()-output_begin).count()<<"}\n";file.flush();
   std::cout<<case_name<<" PASS core="<<core<<" drain="<<drain<<"\n";
  }
  return 0;
 } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
