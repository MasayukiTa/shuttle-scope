// byte_tracker_test.cpp — ByteTracker C++ port の単体テスト。
// tests/golden_byte_tracker.txt と同じ入力で update して、出力 track_id 列と
// bbox 数値 (±1e-3) が一致することを確認する。
//
// 実行:
//   build 後の test 実行ファイルを golden ファイルと同じディレクトリで起動するか、
//   引数で golden path を指定する。デフォルトは ../tests/golden_byte_tracker.txt
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <tuple>
#include <vector>

#include "byte_tracker.h"

using namespace person_tracker_native;

struct GoldenRow {
    int frame_id;
    int track_id;
    float x1, y1, x2, y2;
    float score;
    int is_activated;
};

static std::vector<GoldenRow> load_golden(const std::string& path) {
    std::vector<GoldenRow> rows;
    std::ifstream ifs(path);
    if (!ifs.is_open()) {
        std::fprintf(stderr, "ERROR: cannot open golden file: %s\n", path.c_str());
        std::exit(2);
    }
    std::string line;
    while (std::getline(ifs, line)) {
        if (line.empty() || line[0] == '#') continue;
        std::istringstream iss(line);
        GoldenRow r;
        iss >> r.frame_id >> r.track_id >> r.x1 >> r.y1 >> r.x2 >> r.y2 >> r.score >> r.is_activated;
        rows.push_back(r);
    }
    return rows;
}

int main(int argc, char** argv) {
    std::string golden_path = "../tests/golden_byte_tracker.txt";
    if (argc >= 2) golden_path = argv[1];

    auto golden = load_golden(golden_path);
    std::printf("loaded golden rows: %zu from %s\n", golden.size(), golden_path.c_str());

    // gen_golden.py と同じ scenario (固定)
    std::vector<std::vector<std::tuple<float, float, float, float, float>>> frames = {
        {{100.0f, 200.0f, 200.0f, 400.0f, 0.9f}, {300.0f, 200.0f, 400.0f, 400.0f, 0.85f}},
        {{105.0f, 200.0f, 205.0f, 400.0f, 0.9f}, {305.0f, 200.0f, 405.0f, 400.0f, 0.85f}},
        {{110.0f, 200.0f, 210.0f, 400.0f, 0.9f}, {310.0f, 200.0f, 410.0f, 400.0f, 0.85f}},
        {{115.0f, 200.0f, 215.0f, 400.0f, 0.9f}},
        {{120.0f, 200.0f, 220.0f, 400.0f, 0.9f}, {320.0f, 200.0f, 420.0f, 400.0f, 0.85f}},
    };

    auto* tr = bt_create(60, 120, 0.8f, 0.5f, 0.7f);

    int fails = 0;
    int row_cursor = 0;
    for (int fid = 0; fid < (int)frames.size(); ++fid) {
        std::vector<DetIn> dets;
        for (auto& d : frames[fid]) {
            DetIn di;
            di.x1 = std::get<0>(d);
            di.y1 = std::get<1>(d);
            di.x2 = std::get<2>(d);
            di.y2 = std::get<3>(d);
            di.score = std::get<4>(d);
            dets.push_back(di);
        }
        std::vector<TrackOut> out(16);
        int n = bt_update(tr, dets.data(), (int)dets.size(), fid, out.data(), 16);

        // golden の対応 frame 行を取り出す
        std::vector<GoldenRow> g_this;
        while (row_cursor < (int)golden.size() && golden[row_cursor].frame_id == fid) {
            g_this.push_back(golden[row_cursor++]);
        }
        std::printf("frame=%d cpp_n=%d golden_n=%zu\n", fid, n, g_this.size());
        if ((int)g_this.size() != n) {
            std::fprintf(stderr, "  FAIL: track count mismatch (cpp=%d golden=%zu)\n", n, g_this.size());
            ++fails;
            continue;
        }
        // track_id 順で比較 (Python 側も append 順だが安全に sort)
        std::sort(out.begin(), out.begin() + n,
                  [](const TrackOut& a, const TrackOut& b) { return a.track_id < b.track_id; });
        std::sort(g_this.begin(), g_this.end(),
                  [](const GoldenRow& a, const GoldenRow& b) { return a.track_id < b.track_id; });
        for (int i = 0; i < n; ++i) {
            auto& o = out[i];
            auto& g = g_this[i];
            std::printf("  cpp:  id=%d xyxy=(%.4f,%.4f,%.4f,%.4f) score=%.4f act=%d\n",
                        o.track_id, o.x1, o.y1, o.x2, o.y2, o.score, (int)o.is_activated);
            std::printf("  gold: id=%d xyxy=(%.4f,%.4f,%.4f,%.4f) score=%.4f act=%d\n",
                        g.track_id, g.x1, g.y1, g.x2, g.y2, g.score, g.is_activated);
            if (o.track_id != g.track_id) {
                std::fprintf(stderr, "  FAIL: track_id mismatch\n");
                ++fails;
            }
            auto close = [](float a, float b) { return std::fabs(a - b) <= 1e-3f; };
            if (!close(o.x1, g.x1) || !close(o.y1, g.y1) || !close(o.x2, g.x2) || !close(o.y2, g.y2)) {
                std::fprintf(stderr, "  FAIL: bbox mismatch (tol=1e-3)\n");
                ++fails;
            }
            if (!close(o.score, g.score)) {
                std::fprintf(stderr, "  FAIL: score mismatch\n");
                ++fails;
            }
            if ((int)o.is_activated != g.is_activated) {
                std::fprintf(stderr, "  FAIL: is_activated mismatch\n");
                ++fails;
            }
        }
    }
    bt_destroy(tr);

    if (fails > 0) {
        std::fprintf(stderr, "TEST FAILED with %d errors\n", fails);
        return 1;
    }
    std::printf("TEST PASSED\n");
    return 0;
}
