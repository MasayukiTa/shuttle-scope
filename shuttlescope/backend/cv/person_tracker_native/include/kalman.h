// Kalman filter (constant-velocity, 8 state)。
// Python _KalmanFilter (SORT 流) と等価。
//   state = [cx, cy, a, h, vcx, vcy, va, vh]
//   measurement = [cx, cy, a, h]
//   遷移 F = I8 + dt*[[0,I4],[0,0]]
//   観測 H = [I4 | 0]
// Eigen 非依存、固定 8x8 / 4x4 行列を素直に展開する。
#pragma once

#include <array>

namespace person_tracker_native {

struct KalmanState {
    // 8 次元平均
    std::array<double, 8> mean{};
    // 8x8 共分散 (row-major)
    std::array<double, 64> cov{};
};

class KalmanFilter {
public:
    KalmanFilter();

    // 初期化: 測定値から state 起こす
    KalmanState initiate(const std::array<double, 4>& measurement) const;

    // 1 step 予測
    void predict(KalmanState& s) const;

    // 観測 update
    void update(KalmanState& s, const std::array<double, 4>& measurement) const;

private:
    double std_weight_position_;
    double std_weight_velocity_;
};

}  // namespace person_tracker_native
