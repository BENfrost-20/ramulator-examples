#pragma once

#include <cmath>
#include <cstdint>
#include <functional>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>

#include "ramulator/base/factory.h"
#include "ramulator/bambu/legacy_config.h"
#include "ramulator/frontend/i_frontend.h"

class RamulatorTiming {
public:
    RamulatorTiming(const char* path, long double period_ns) {
        auto config = YAML::LoadFile(path);
        auto native = Ramulator::Bambu::native_configuration(config);
        if (native["frontend"]["impl"].as<std::string>() != "External") {
            throw std::runtime_error("The Ramulator AXI bridge requires the External frontend");
        }
        native["frontend"]["clock_ratio"] = 1;
        native["memory_system"]["clock_ratio"] = 1;
        const auto factory_config = Ramulator::Bambu::factory_configuration(native);
        frontend_.reset(Ramulator::Factory::create_frontend(factory_config));
        memory_.reset(Ramulator::Factory::create_memory_system(factory_config));
        frontend_->connect_memory_system(memory_.get());
        memory_->connect_frontend(frontend_.get());
        // MDPI recovers the integer DRAM period in ps from its float ns API.
        tick_period_ = std::round(static_cast<long double>(memory_->get_tCK()) * 1000) * 1000;
        cycle_step_ = std::round(period_ns * 1000000);
        if (!std::isfinite(tick_period_) || tick_period_ <= 0
                || !std::isfinite(cycle_step_) || cycle_step_ <= 0) {
            throw std::runtime_error("The AXI and DRAM clocks must be finite and positive");
        }
    }

    void advance_cycle() {
        phase_ += cycle_step_;
        while (phase_ >= tick_period_) {
            phase_ -= tick_period_;
            ++ticks_;
            memory_->tick();
        }
    }

    bool read(std::uint64_t address, int bytes, std::function<void(Ramulator::Request&)> completion) {
        return request(Ramulator::Request::Type::Read, address, bytes, std::move(completion));
    }

    bool write(std::uint64_t address, int bytes) {
        return request(Ramulator::Request::Type::Write, address, bytes, {});
    }

    long double ratio() const { return cycle_step_ / tick_period_; }
    std::uint64_t ticks() const { return ticks_; }

private:
    bool request(int type, std::uint64_t address, int bytes,
                 std::function<void(Ramulator::Request&)> completion) {
        return frontend_->receive_external_requests(type, address, 0, std::move(completion), bytes);
    }

    std::unique_ptr<Ramulator::IFrontEnd> frontend_;
    std::unique_ptr<Ramulator::IMemorySystem> memory_;
    long double cycle_step_ = 0;
    long double tick_period_ = 1;
    long double phase_ = 0;
    std::uint64_t ticks_ = 0;
};
