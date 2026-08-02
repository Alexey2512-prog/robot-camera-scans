#include <librealsense2/rs.hpp>

#include <chrono>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

double percentile(std::vector<double> values, double percent) {
    if (values.empty()) return 0.0;
    std::sort(values.begin(), values.end());
    if (values.size() == 1) return values.front();
    const double position = (values.size() - 1) * percent / 100.0;
    const auto lower = static_cast<std::size_t>(std::floor(position));
    const auto upper = static_cast<std::size_t>(std::ceil(position));
    if (lower == upper) return values[lower];
    const double weight = position - lower;
    return values[lower] * (1.0 - weight) + values[upper] * weight;
}

int main(int argc, char** argv) {
    if (argc != 3) {
        std::cerr << "Usage: rs-frame-test SERIAL DURATION_SECONDS\n";
        return 2;
    }

    const std::string serial = argv[1];
    const double duration_seconds = std::stod(argv[2]);
    if (duration_seconds <= 0.0 || duration_seconds > 60.0) {
        std::cerr << "Duration must be greater than 0 and no more than 60 seconds\n";
        return 2;
    }

    try {
        rs2::context context;
        bool device_found = false;
        for (auto&& device : context.query_devices()) {
            if (device.supports(RS2_CAMERA_INFO_SERIAL_NUMBER) &&
                serial == device.get_info(RS2_CAMERA_INFO_SERIAL_NUMBER)) {
                device_found = true;
                break;
            }
        }

        if (!device_found) {
            throw std::runtime_error("RealSense device with this serial was not found");
        }

        rs2::pipeline pipeline(context);
        rs2::config config;
        config.enable_device(serial);
        config.enable_stream(RS2_STREAM_DEPTH);

        const rs2::pipeline_profile profile = pipeline.start(config);
        const int target_fps = profile.get_stream(RS2_STREAM_DEPTH).fps();

        // Discard startup frames so initialization is not included in FPS.
        for (int i = 0; i < 5; ++i) {
            pipeline.wait_for_frames(5000);
        }

        using clock = std::chrono::steady_clock;
        const auto started_at = clock::now();
        auto finished_at = started_at;
        std::uint64_t received = 0;
        std::uint64_t dropped = 0;
        std::uint64_t previous_sequence = 0;
        std::uint64_t max_consecutive_drops = 0;
        std::vector<double> arrivals;

        while (std::chrono::duration<double>(finished_at - started_at).count() <
               duration_seconds) {
            const rs2::frameset frames = pipeline.wait_for_frames(5000);
            const rs2::depth_frame depth = frames.get_depth_frame();
            finished_at = clock::now();

            if (!depth) {
                continue;
            }

            const std::uint64_t sequence = depth.get_frame_number();
            if (previous_sequence != 0 && sequence > previous_sequence + 1) {
                const std::uint64_t gap = sequence - previous_sequence - 1;
                dropped += gap;
                max_consecutive_drops = std::max(max_consecutive_drops, gap);
            }
            previous_sequence = sequence;
            arrivals.push_back(
                std::chrono::duration<double>(finished_at.time_since_epoch()).count());
            ++received;
        }

        pipeline.stop();

        const double elapsed = arrivals.size() > 1
                                   ? arrivals.back() - arrivals.front()
                                   : 0.0;
        const double actual_fps = elapsed > 0.0
                                      ? (arrivals.size() - 1) / elapsed
                                      : 0.0;
        const std::uint64_t expected_total = received + dropped;
        const double drop_percent = expected_total > 0
                                        ? 100.0 * dropped / expected_total
                                        : 0.0;

        std::vector<double> intervals_ms;
        for (std::size_t index = 1; index < arrivals.size(); ++index) {
            intervals_ms.push_back((arrivals[index] - arrivals[index - 1]) * 1000.0);
        }
        double interval_average = 0.0;
        for (const double interval : intervals_ms) interval_average += interval;
        if (!intervals_ms.empty()) interval_average /= intervals_ms.size();
        const double interval_p95 = percentile(intervals_ms, 95.0);
        const double interval_median = percentile(intervals_ms, 50.0);
        std::vector<double> jitter_ms;
        for (const double interval : intervals_ms) {
            jitter_ms.push_back(std::abs(interval - interval_median));
        }
        const double jitter_p95 = percentile(jitter_ms, 95.0);
        const double max_gap = intervals_ms.empty()
                                   ? 0.0
                                   : *std::max_element(intervals_ms.begin(), intervals_ms.end());

        std::cout << std::fixed << std::setprecision(3) << actual_fps << '\t'
                  << received << '\t' << dropped << '\t' << drop_percent << '\t'
                  << target_fps << '\t' << interval_average << '\t'
                  << interval_p95 << '\t' << jitter_p95 << '\t' << max_gap << '\t'
                  << max_consecutive_drops << '\n';
        return 0;
    } catch (const rs2::error& error) {
        std::cerr << error.what() << '\n';
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
    }

    return 1;
}
