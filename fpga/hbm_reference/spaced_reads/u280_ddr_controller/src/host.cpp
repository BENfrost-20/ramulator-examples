#include "ddr_address.hpp"
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
#include <filesystem>
#include <fstream>
#include <vector>
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
  if (argc != 4) throw std::runtime_error("Usage: host XCLBIN PCI_BDF NEW_RESULTS_DIRECTORY");
  const std::filesystem::path out_dir(argv[3]);
  if (!std::filesystem::create_directory(out_dir))
    throw std::runtime_error("Results directory already exists");
  xrt::device device{std::string(argv[2])};
  xrt::xclbin image{std::string(argv[1])};
  auto uuid = device.load_xclbin(image);
  xrt::ip ip(device, uuid, "fpga_kernel:{fpga_kernel_1}");
  if (ip.read_register(0x90) != 0x52444632 || (ip.read_register(0) & 1))
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
  xrt::bo bo(device, ddr::slab_size, xrt::bo::flags::normal, bank);
  InFlight guard;
  const auto bo_base = bo.address();
  if (bo_base < ddr::aperture || bo_base > ddr::aperture + ddr::capacity - ddr::slab_size)
    throw std::runtime_error("BO falls outside the DDR[0] aperture");
  const auto base = (bo_base + ddr::alignment - 1) & ~(ddr::alignment - 1);
  if (!ddr::valid_anchor(base) || (base ^ ddr::masks[1]) + 4 > bo_base + ddr::slab_size)
    throw std::runtime_error("Aligned address pair falls outside the BO");
  std::vector<std::uint32_t> data(ddr::slab_size / sizeof(std::uint32_t));
  data.at((base - bo_base) / 4) = ddr::word_a;
  for (auto mask : ddr::masks) data.at(((base ^ mask) - bo_base) / 4) = ddr::word_b;
  std::ofstream placement(out_dir / "placement.tsv");
  placement << "bo_address\tanchor\ttopology_index\n"
            << std::hex << "0x" << bo_base << "\t0x" << base << std::dec << '\t' << bank << '\n';
  placement.close();
  if (!placement) throw std::runtime_error("Cannot record BO placement");
  std::cout << "BO address: 0x" << std::hex << bo_base
            << " anchor: 0x" << base << std::dec << '\n';
  for (unsigned repeat = 0; repeat < 3; ++repeat) {
    for (unsigned slot = 0; slot < ddr::names.size(); ++slot) {
      const auto mode = (repeat + slot) % ddr::names.size();
      bo.write(data.data(), ddr::slab_size, 0);
      bo.sync(XCL_BO_SYNC_BO_TO_DEVICE);
      ip.write_register(0x10, mode);
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
      const auto csv_name = std::string(ddr::names[mode]) + "-" + std::to_string(repeat + 1) + ".csv";
      std::ofstream out(out_dir / csv_name);
      if (!out) throw std::runtime_error("Cannot open result");
      out << "sample,ar_cycle,rvalid_cycle,r_cycle,latency_cycles,axi_address\n";
      std::uint32_t previous = 0;
      for (unsigned i = 0; i < 1000; ++i) {
        ip.write_register(0x10, i);
        auto ar = ip.read_register(0x94), r = ip.read_register(0x98);
        if (r <= ar || ar < previous + (i ? 8 : 50)) throw std::runtime_error("Invalid or overlapping sample");
        out << i+1 << ',' << ar << ',' << r << ',' << r << ',' << r-ar << ",0x"
            << std::hex << (base ^ (i % 2 ? ddr::masks[mode] : 0)) << std::dec << '\n';
        previous = r;
      }
      out.close();
      if (!out) throw std::runtime_error("Result write failed");
      std::cout << "PASS 1000 AXI reads " << csv_name << '\n';
    }
  }
  return 0;
} catch (const std::exception& e) {
  std::cerr << e.what() << '\n';
  return 1;
}
