#pragma once

#include <cmath>
#include <cstdint>
#include <functional>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>

#include "base/config.h"
#include "frontend/frontend.h"

class RamulatorTiming {
public:
    explicit RamulatorTiming(const char* path) {
        auto config = YAML::LoadFile(path);
        if (config["Frontend"]["impl"].as<std::string>() != "GEM5") {
            throw std::runtime_error("The Ramulator AXI bridge requires the GEM5 frontend");
        }
        auto system = config["MemorySystem"];
        ratio_ = system["clock_ratio"].as<long double>();
        if (!std::isfinite(ratio_) || ratio_ <= 0) {
            throw std::runtime_error("MemorySystem.clock_ratio must be finite and positive");
        }
        // The bridge advances the memory clock directly, including fractional ratios.
        system["clock_ratio"] = 1;
        frontend_.reset(Ramulator::Factory::create_frontend(config));
        memory_.reset(Ramulator::Factory::create_memory_system(config));
        frontend_->connect_memory_system(memory_.get());
        memory_->connect_frontend(frontend_.get());
    }

    void advance_cycle() {
        phase_ += ratio_;
        constexpr auto tolerance = 16 * std::numeric_limits<long double>::epsilon();
        while (phase_ + tolerance >= 1) {
            phase_ -= 1;
            ++ticks_;
            memory_->tick();
        }
    }

    bool read(std::uint64_t address, std::function<void(Ramulator::Request&)> completion) {
        return frontend_->receive_external_requests(Ramulator::Request::Type::Read,
                                                    address, 0, std::move(completion));
    }

    bool write(std::uint64_t address) {
        return frontend_->receive_external_requests(Ramulator::Request::Type::Write,
                                                    address, 0, {});
    }

    long double ratio() const { return ratio_; }
    std::uint64_t ticks() const { return ticks_; }

private:
    std::unique_ptr<Ramulator::IFrontEnd> frontend_;
    std::unique_ptr<Ramulator::IMemorySystem> memory_;
    long double ratio_ = 0;
    long double phase_ = 0;
    std::uint64_t ticks_ = 0;
};
