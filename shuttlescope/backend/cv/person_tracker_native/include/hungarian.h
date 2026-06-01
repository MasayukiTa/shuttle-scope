// Hungarian (Munkres) algorithm。
// cost 行列を最小化する row -> col 割当てを返す。
// 矩形対応 (rows != cols 可)。
// 計算量 O(n^3)。tracker の N は数十なので問題なし。
#pragma once

#include <vector>

namespace person_tracker_native {

// cost: n_rows * n_cols (row-major)
// assignment[r] = c (matched) or -1 (unmatched)
// 戻り値長さ = n_rows
std::vector<int> hungarian_solve(const std::vector<double>& cost, int n_rows, int n_cols);

}  // namespace person_tracker_native
