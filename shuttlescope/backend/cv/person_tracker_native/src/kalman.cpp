// Kalman filter 実装。Python _KalmanFilter と数値的に同等。
#include "kalman.h"

#include <array>
#include <cmath>

namespace person_tracker_native {

namespace {

// 8x8 行列積 C = A * B (row-major)
inline void mm8(const double* A, const double* B, double* C) {
    for (int i = 0; i < 8; ++i) {
        for (int j = 0; j < 8; ++j) {
            double s = 0.0;
            for (int k = 0; k < 8; ++k) s += A[i * 8 + k] * B[k * 8 + j];
            C[i * 8 + j] = s;
        }
    }
}

// 4x4 inverse (Gauss-Jordan)。innovation cov は対称正定値で十分小さいので OK。
inline bool inv4(const double* M, double* Inv) {
    double a[4][8];
    for (int i = 0; i < 4; ++i) {
        for (int j = 0; j < 4; ++j) a[i][j] = M[i * 4 + j];
        for (int j = 0; j < 4; ++j) a[i][4 + j] = (i == j) ? 1.0 : 0.0;
    }
    for (int i = 0; i < 4; ++i) {
        // pivot
        int piv = i;
        double maxv = std::fabs(a[i][i]);
        for (int r = i + 1; r < 4; ++r) {
            if (std::fabs(a[r][i]) > maxv) { maxv = std::fabs(a[r][i]); piv = r; }
        }
        if (maxv < 1e-12) return false;
        if (piv != i) {
            for (int j = 0; j < 8; ++j) std::swap(a[i][j], a[piv][j]);
        }
        double inv = 1.0 / a[i][i];
        for (int j = 0; j < 8; ++j) a[i][j] *= inv;
        for (int r = 0; r < 4; ++r) {
            if (r == i) continue;
            double f = a[r][i];
            for (int j = 0; j < 8; ++j) a[r][j] -= f * a[i][j];
        }
    }
    for (int i = 0; i < 4; ++i) for (int j = 0; j < 4; ++j) Inv[i * 4 + j] = a[i][4 + j];
    return true;
}

}  // namespace

KalmanFilter::KalmanFilter()
    : std_weight_position_(1.0 / 20.0), std_weight_velocity_(1.0 / 160.0) {}

KalmanState KalmanFilter::initiate(const std::array<double, 4>& m) const {
    KalmanState s{};
    for (int i = 0; i < 4; ++i) s.mean[i] = m[i];
    for (int i = 4; i < 8; ++i) s.mean[i] = 0.0;
    double h = m[3];
    double std_arr[8] = {
        2.0 * std_weight_position_ * h,
        2.0 * std_weight_position_ * h,
        1e-2,
        2.0 * std_weight_position_ * h,
        10.0 * std_weight_velocity_ * h,
        10.0 * std_weight_velocity_ * h,
        1e-5,
        10.0 * std_weight_velocity_ * h,
    };
    for (int i = 0; i < 64; ++i) s.cov[i] = 0.0;
    for (int i = 0; i < 8; ++i) s.cov[i * 8 + i] = std_arr[i] * std_arr[i];
    return s;
}

void KalmanFilter::predict(KalmanState& s) const {
    // F = I8、上三角に dt(=1) を ndim=4 ぶん加える: F[i, ndim+i] = 1
    // よって new_mean[i] = mean[i] + mean[i+4] (i<4)、new_mean[i]=mean[i] (i>=4)
    std::array<double, 8> new_mean{};
    for (int i = 0; i < 4; ++i) new_mean[i] = s.mean[i] + s.mean[i + 4];
    for (int i = 4; i < 8; ++i) new_mean[i] = s.mean[i];

    // F P F^T。F は I + N (N は I4 を i, i+4 に置く). 簡便のため明示行列で計算。
    double F[64] = {0};
    for (int i = 0; i < 8; ++i) F[i * 8 + i] = 1.0;
    for (int i = 0; i < 4; ++i) F[i * 8 + (4 + i)] = 1.0;

    double FP[64];
    mm8(F, s.cov.data(), FP);
    // FP * F^T (F^T は F の転置)
    double Ft[64];
    for (int i = 0; i < 8; ++i) for (int j = 0; j < 8; ++j) Ft[i * 8 + j] = F[j * 8 + i];
    double FPFt[64];
    mm8(FP, Ft, FPFt);

    double h = s.mean[3];
    double std_pos[4] = {
        std_weight_position_ * h,
        std_weight_position_ * h,
        1e-2,
        std_weight_position_ * h,
    };
    double std_vel[4] = {
        std_weight_velocity_ * h,
        std_weight_velocity_ * h,
        1e-5,
        std_weight_velocity_ * h,
    };
    double q[8];
    for (int i = 0; i < 4; ++i) q[i] = std_pos[i] * std_pos[i];
    for (int i = 0; i < 4; ++i) q[4 + i] = std_vel[i] * std_vel[i];

    for (int i = 0; i < 64; ++i) s.cov[i] = FPFt[i];
    for (int i = 0; i < 8; ++i) s.cov[i * 8 + i] += q[i];
    s.mean = new_mean;
}

void KalmanFilter::update(KalmanState& s, const std::array<double, 4>& meas) const {
    // 観測 H = [I4 | 0]。よって H*mean = mean[0..4]、H*P = P の上半 4 行。
    double h = s.mean[3];
    double std_arr[4] = {
        std_weight_position_ * h,
        std_weight_position_ * h,
        1e-1,
        std_weight_position_ * h,
    };
    double R[16] = {0};
    for (int i = 0; i < 4; ++i) R[i * 4 + i] = std_arr[i] * std_arr[i];

    // projected_mean = mean[0..4]
    double pmean[4];
    for (int i = 0; i < 4; ++i) pmean[i] = s.mean[i];

    // projected_cov = H P H^T + R = P[0..4, 0..4] + R
    double S[16];
    for (int i = 0; i < 4; ++i) for (int j = 0; j < 4; ++j) S[i * 4 + j] = s.cov[i * 8 + j] + R[i * 4 + j];

    double Sinv[16];
    inv4(S, Sinv);

    // Kalman gain K = P H^T S^{-1} = P[:, 0..4] * S^{-1}, shape 8x4
    double PHt[32];  // 8x4
    for (int i = 0; i < 8; ++i) for (int j = 0; j < 4; ++j) PHt[i * 4 + j] = s.cov[i * 8 + j];
    double K[32];  // 8x4
    for (int i = 0; i < 8; ++i) {
        for (int j = 0; j < 4; ++j) {
            double sum = 0.0;
            for (int k = 0; k < 4; ++k) sum += PHt[i * 4 + k] * Sinv[k * 4 + j];
            K[i * 4 + j] = sum;
        }
    }

    // innovation = meas - pmean
    double y[4];
    for (int i = 0; i < 4; ++i) y[i] = meas[i] - pmean[i];

    // new_mean = mean + K * y  (8)
    std::array<double, 8> new_mean{};
    for (int i = 0; i < 8; ++i) {
        double sum = s.mean[i];
        for (int j = 0; j < 4; ++j) sum += K[i * 4 + j] * y[j];
        new_mean[i] = sum;
    }

    // new_cov = P - K * H * P  = P - K * P[0..4, :]
    // K(8x4) * P[0..4,:](4x8) -> 8x8
    double KHP[64];
    for (int i = 0; i < 8; ++i) {
        for (int j = 0; j < 8; ++j) {
            double sum = 0.0;
            for (int k = 0; k < 4; ++k) sum += K[i * 4 + k] * s.cov[k * 8 + j];
            KHP[i * 8 + j] = sum;
        }
    }
    for (int i = 0; i < 64; ++i) s.cov[i] -= KHP[i];
    s.mean = new_mean;
}

}  // namespace person_tracker_native
