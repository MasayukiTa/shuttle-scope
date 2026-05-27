// Hungarian / Munkres algorithm。
// O(n^3)、矩形対応 (n_rows != n_cols)。
// scipy.optimize.linear_sum_assignment と同一の最適コスト割当てを返す
// (最適解が複数ある場合、選ばれる組合せは tie-break で異なりうるが、
//  IoU マッチング用途では IoU 1.0 同点はほぼ起きないので実害なし)。
//
// 実装は Bipartite shortest-path Hungarian (kuhn-munkres) を採用。
// 参考: https://en.wikipedia.org/wiki/Hungarian_algorithm 、cp-algorithms。
#include "hungarian.h"

#include <algorithm>
#include <limits>
#include <vector>

namespace person_tracker_native {

std::vector<int> hungarian_solve(const std::vector<double>& cost_in, int n_rows, int n_cols) {
    if (n_rows == 0 || n_cols == 0) {
        return std::vector<int>(n_rows, -1);
    }
    // n x m へ正方化 (n <= m を要求)。
    bool transposed = false;
    int n = n_rows;
    int m = n_cols;
    std::vector<double> cost;
    if (n > m) {
        // 転置
        transposed = true;
        n = n_cols;
        m = n_rows;
        cost.assign(n * m, 0.0);
        for (int i = 0; i < n; ++i)
            for (int j = 0; j < m; ++j)
                cost[i * m + j] = cost_in[j * n_cols + i];
    } else {
        cost = cost_in;
    }

    const double INF = std::numeric_limits<double>::infinity();
    // u: n+1, v: m+1, p: m+1, way: m+1 (1-indexed)
    std::vector<double> u(n + 1, 0.0), v(m + 1, 0.0);
    std::vector<int> p(m + 1, 0), way(m + 1, 0);
    for (int i = 1; i <= n; ++i) {
        p[0] = i;
        int j0 = 0;
        std::vector<double> minv(m + 1, INF);
        std::vector<char> used(m + 1, false);
        do {
            used[j0] = true;
            int i0 = p[j0];
            double delta = INF;
            int j1 = -1;
            for (int j = 1; j <= m; ++j) {
                if (used[j]) continue;
                double cur = cost[(i0 - 1) * m + (j - 1)] - u[i0] - v[j];
                if (cur < minv[j]) {
                    minv[j] = cur;
                    way[j] = j0;
                }
                if (minv[j] < delta) {
                    delta = minv[j];
                    j1 = j;
                }
            }
            for (int j = 0; j <= m; ++j) {
                if (used[j]) {
                    u[p[j]] += delta;
                    v[j] -= delta;
                } else {
                    minv[j] -= delta;
                }
            }
            j0 = j1;
        } while (p[j0] != 0);
        do {
            int j1 = way[j0];
            p[j0] = p[j1];
            j0 = j1;
        } while (j0 != 0);
    }
    // ans[row] = col、row は 0-indexed
    std::vector<int> ans(n, -1);
    for (int j = 1; j <= m; ++j) {
        if (p[j] != 0) ans[p[j] - 1] = j - 1;
    }
    // 元の n_rows サイズの結果に戻す
    if (transposed) {
        std::vector<int> result(n_rows, -1);
        for (int i = 0; i < n; ++i) {
            int j = ans[i];
            if (j >= 0) result[j] = i;  // ans は col->row (転置後の row=元の col)
        }
        return result;
    }
    return ans;
}

}  // namespace person_tracker_native
