#pragma once

#include <iostream>

#include "dram_controller/controller.h"
#include "dram_controller/plugin.h"

namespace Ramulator {
class U280DDRCommandTrace final : public IControllerPlugin, public Implementation {
    RAMULATOR_REGISTER_IMPLEMENTATION(IControllerPlugin, U280DDRCommandTrace,
                                      "U280DDRCommandTrace", "Print issued DDR4 commands and coordinates.")
public:
    void init() override {}

    void setup(IFrontEnd*, IMemorySystem*) override {
        m_ctrl = cast_parent<IDRAMController>();
    }

    void update(bool request_found, ReqBuffer::iterator& request) override {
        ++tick_;
        if (!request_found) return;
        std::cerr << "DRAM_CMD," << tick_ << ',' << m_ctrl->m_dram->m_commands(request->command);
        for (auto coordinate : request->addr_vec) std::cerr << ',' << coordinate;
        std::cerr << '\n';
    }

private:
    std::uint64_t tick_ = 0;
};
}
