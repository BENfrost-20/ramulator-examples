#include <xrt/xrt_device.h>
#include <xrt/xrt_bo.h>
#if __has_include(<xrt/experimental/xrt_ip.h>)
#include <xrt/experimental/xrt_ip.h>
#include <xrt/experimental/xrt_xclbin.h>
#else
#include <experimental/xrt_ip.h>
#include <experimental/xrt_xclbin.h>
#endif
#include <array>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <thread>

struct InFlight {
  bool active = false;
  ~InFlight() {
    if (active) {
      std::cerr << "Accelerator may still read from its BO. Keep this process alive and contact HACC support.\n";
      for (;;) std::this_thread::sleep_for(std::chrono::seconds(1));
    }
  }
};

int main(int argc, char** argv) try {
  if (argc != 4) throw std::runtime_error("Usage: host XCLBIN PCI_BDF NEW_CSV");
  std::ifstream existing(argv[3]);
  if (existing.good()) throw std::runtime_error("Refusing to overwrite result");
  xrt::device device{std::string(argv[2])};
  xrt::xclbin image{std::string(argv[1])};
  auto uuid = device.load_xclbin(image);
  xrt::ip ip(device, uuid, "fpga_kernel:{fpga_kernel_1}");
  if (ip.read_register(0x90) != 0x52444631 || (ip.read_register(0) & 1))
    throw std::runtime_error("Unexpected probe signature or busy kernel");
  auto ips = image.get_ips("fpga_kernel:{fpga_kernel_1}");
  if (ips.size()!=1) throw std::runtime_error("Expected one probe CU");
  int bank = -1;
  for (const auto& arg : ips[0].get_args()) {
    if (arg.get_name() != "base0") continue;
    auto mem = arg.get_mems();
    if (mem.size()!=1 || !mem[0].get_used())
      throw std::runtime_error("Expected one used topology bank for base0");
    bank = mem[0].get_index();
  }
  if (bank < 0) throw std::runtime_error("Missing base0 topology index");
  xrt::bo bo(device, 65536, xrt::bo::flags::normal, bank);
  InFlight guard;
  std::array<std::uint32_t, 16384> data{};
  data[64] = 0x12345678;
  bo.write(data.data(), sizeof(data), 0);
  bo.sync(XCL_BO_SYNC_BO_TO_DEVICE);
  auto base = bo.address() + 256;
  std::cout << "BO read address: 0x" << std::hex << base << std::dec << '\n';
  ip.write_register(0x20, std::uint32_t(base));
  ip.write_register(0x24, std::uint32_t(base >> 32));
  auto generation = ip.read_register(4);
  guard.active = true;
  ip.write_register(0, 1);
  auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(60);
  while (true) {
    auto status = ip.read_register(0);
    if (((status & 5) == 4) && ip.read_register(4) == generation + 1) {
      guard.active = false;
      if (status & 8) throw std::runtime_error("AXI response or data check failed");
      break;
    }
    if (std::chrono::steady_clock::now() > deadline) throw std::runtime_error("Probe timed out");
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
  std::ofstream out(argv[3]);
  if (!out) throw std::runtime_error("Cannot open result");
  out << "sample,ar_cycle,rvalid_cycle,r_cycle,latency_cycles\n";
  std::uint32_t previous = 0;
  for (unsigned i = 0; i < 1000; ++i) {
    ip.write_register(0x10, i);
    auto ar = ip.read_register(0x94), r = ip.read_register(0x98);
    if (r <= ar || ar < previous + 50) throw std::runtime_error("Invalid or overlapping sample");
    out << i+1 << ',' << ar << ',' << r << ',' << r << ',' << r-ar << '\n';
    previous = r;
  }
  out.close();
  if (!out) throw std::runtime_error("Result write failed");
  std::cout << "PASS 1000 AXI reads\n";
  return 0;
} catch (const std::exception& e) {
  std::cerr << e.what() << '\n';
  return 1;
}
