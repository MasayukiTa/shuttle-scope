// detector_test.cpp — Phase A1 単体テスト
// preprocess (CUDA) → detector (ORT TRT EP) パイプラインを 1 度通し、
// 出力 shape と簡易ベンチ (fps) を表示する。
//
// 使い方:
//   detector_test.exe [onnx_path]
// 既定: ../shuttlescope/backend/models/yolov8n_v2_finetuned_dyn.onnx
//        fallback: yolov8n.onnx
//
// dummy input は 1920x1080 uint8 BGR (B=4) を生成し、384x640 にリサイズする。

#include "preprocess.h"
#include "detector.h"

#include <cuda_runtime.h>
#include <cuda_fp16.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <chrono>
#include <vector>
#include <string>
#include <filesystem>

using namespace person_tracker_native;

static std::string find_model(const std::string& explicit_path) {
    namespace fs = std::filesystem;
    if (!explicit_path.empty() && fs::exists(explicit_path)) return explicit_path;

    // 既定候補 (repo の典型レイアウト)
    const std::vector<std::string> candidates = {
        "shuttlescope/backend/models/yolov8n_v2_finetuned_dyn.onnx",
        "../shuttlescope/backend/models/yolov8n_v2_finetuned_dyn.onnx",
        "../../shuttlescope/backend/models/yolov8n_v2_finetuned_dyn.onnx",
        "../../../shuttlescope/backend/models/yolov8n_v2_finetuned_dyn.onnx",
        "shuttlescope/backend/models/yolov8n.onnx",
        "../shuttlescope/backend/models/yolov8n.onnx",
        "../../shuttlescope/backend/models/yolov8n.onnx",
        "../../../shuttlescope/backend/models/yolov8n.onnx",
        "../../../../shuttlescope/backend/models/yolov8n.onnx",
    };
    for (const auto& c : candidates) {
        if (fs::exists(c)) return fs::absolute(c).string();
    }
    return "";
}

int main(int argc, char** argv) {
    const std::string arg_path = (argc >= 2) ? argv[1] : "";
    const std::string model_path = find_model(arg_path);
    if (model_path.empty()) {
        std::fprintf(stderr, "[test] model not found. give path as arg1.\n");
        return 2;
    }
    std::fprintf(stderr, "[test] model: %s\n", model_path.c_str());

    const int B = 4;
    const int H_src = 1080, W_src = 1920;
    const int H_dst = 384,  W_dst = 640;
    const bool fp16 = true;

    // dummy frames (host)
    std::vector<std::vector<uint8_t>> frames(B);
    std::vector<const uint8_t*> frame_ptrs(B);
    for (int b = 0; b < B; ++b) {
        frames[b].assign((size_t)H_src * W_src * 3, 0);
        // 適当な勾配 pattern を入れる
        for (size_t i = 0; i < frames[b].size(); ++i) {
            frames[b][i] = static_cast<uint8_t>((i + b * 17) & 0xFF);
        }
        frame_ptrs[b] = frames[b].data();
    }

    // preprocess
    auto* pp = preprocess_create(B, H_dst, W_dst, fp16);
    void* d_in = preprocess_run(pp, frame_ptrs.data(), B, H_src, W_src);
    std::fprintf(stderr, "[test] preprocess done, d_in=%p, elem=%zu\n",
                 d_in, preprocess_elem_size(pp));

    // detector
    auto* det = detector_create(model_path.c_str(), /*cuda_device=*/0,
                                /*use_trt=*/true, fp16);
    DetOutput out = detector_infer(det, d_in, B, H_dst, W_dst);
    std::fprintf(stderr,
        "[test] infer warm: B=%d n_ch=%d n_anchors=%d dev_ptr=%p\n",
        out.B, out.n_ch, out.n_anchors, out.dev_ptr);

    if (out.B != B) {
        std::fprintf(stderr, "[test] FAIL: output batch %d != input %d\n", out.B, B);
        return 1;
    }
    if (out.n_ch < 5) {
        std::fprintf(stderr, "[test] WARN: n_ch=%d (expected >=5 for yolov8)\n", out.n_ch);
    }

    // 簡易ベンチ
    const int N = 50;
    auto t0 = std::chrono::high_resolution_clock::now();
    for (int i = 0; i < N; ++i) {
        void* p = preprocess_run(pp, frame_ptrs.data(), B, H_src, W_src);
        (void)detector_infer(det, p, B, H_dst, W_dst);
    }
    cudaDeviceSynchronize();
    auto t1 = std::chrono::high_resolution_clock::now();
    double ms = std::chrono::duration<double, std::milli>(t1 - t0).count();
    double fps = (double)(N * B) * 1000.0 / ms;
    std::fprintf(stderr, "[test] bench: N=%d B=%d total=%.2f ms => %.1f fps\n",
                 N, B, ms, fps);

    detector_destroy(det);
    preprocess_destroy(pp);
    std::fprintf(stdout, "OK B=%d n_ch=%d n_anchors=%d fps=%.1f\n",
                 out.B, out.n_ch, out.n_anchors, fps);
    return 0;
}
