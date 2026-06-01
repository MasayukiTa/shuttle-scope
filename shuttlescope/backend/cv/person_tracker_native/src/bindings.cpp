// bindings.cpp — pybind11 module (Phase A3)
//
// Python から見える API:
//   ext.BatchDetector(onnx_path, max_batch=32, use_fp16=True, use_trt=True, cuda_device=0)
//       .detect_and_track(frames: np.ndarray uint8 (B,H,W,3), frame_idxs: list[int])
//         -> list[list[tuple(x1, y1, x2, y2, score, track_id)]]
//
// 内部 flow:
//   numpy uint8 BGR (B,H,W,3)
//     -> preprocess_run (CUDA)   : device fp16/fp32 (B,3,H_dst,W_dst)
//     -> detector_infer (ORT)    : device (B, n_ch, n_anchors)
//     -> cudaMemcpy -> host parse: conf threshold + cxcywh→xyxy + scale to src
//     -> bt_update per frame     : track outputs
//
// 出力は frame ごとに (x1, y1, x2, y2, score, track_id) のタプル列を返す。
//
// 設計メモ:
//   * model 入力解像度 (H_dst, W_dst) は ONNX から動的に取得せず、コンストラクタ
//     引数で固定する。yolov8n_v2_finetuned_dyn.onnx は (3, 384, 640) を期待。
//   * 出力 ch 数は 5 (cx, cy, w, h, conf) 想定。84 ch (COCO 80-class) には未対応。
//   * fp16 出力時は host で float に展開して parse する。
//
// Phase A3 (2026-05-27).

#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <pybind11/stl.h>

#include <cuda_runtime.h>
#include <cuda_fp16.h>

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <memory>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

#include "preprocess.h"
#include "detector.h"
#include "byte_tracker.h"

namespace py = pybind11;

namespace person_tracker_native {

namespace {

// fp16 → fp32 変換 (host 側)
inline float half_to_float(uint16_t h) {
    __half hv;
    std::memcpy(&hv, &h, sizeof(uint16_t));
    return __half2float(hv);
}

}  // anonymous namespace

// ─────────────────────────────────────────────────────────────────────────
// BatchDetector: preprocess + detector + bytetracker をひとまとめにした
// Python 公開クラス。
// ─────────────────────────────────────────────────────────────────────────
class BatchDetector {
public:
    BatchDetector(std::string onnx_path,
                  int max_batch,
                  bool use_fp16,
                  bool use_trt,
                  int cuda_device,
                  int h_dst,
                  int w_dst,
                  float conf_thresh)
        : onnx_path_(std::move(onnx_path)),
          max_batch_(max_batch),
          use_fp16_(use_fp16),
          h_dst_(h_dst),
          w_dst_(w_dst),
          conf_thresh_(conf_thresh) {
        pp_ = preprocess_create(max_batch_, h_dst_, w_dst_, use_fp16_);
        if (!pp_) throw std::runtime_error("preprocess_create failed");

        det_ = detector_create(onnx_path_.c_str(), cuda_device, use_trt, use_fp16_);
        if (!det_) {
            preprocess_destroy(pp_);
            pp_ = nullptr;
            throw std::runtime_error("detector_create failed");
        }

        // ByteTracker: Python 側 DEFAULT_CONF=0.25 と整合。
        bt_ = bt_create(/*frame_rate=*/60, /*track_buffer=*/120,
                        /*thresh_high=*/0.8f, /*thresh_low=*/0.5f,
                        /*thresh_unconfirmed=*/0.7f);
        if (!bt_) {
            detector_destroy(det_);
            preprocess_destroy(pp_);
            det_ = nullptr;
            pp_ = nullptr;
            throw std::runtime_error("bt_create failed");
        }
    }

    ~BatchDetector() {
        if (bt_) bt_destroy(bt_);
        if (det_) detector_destroy(det_);
        if (pp_) preprocess_destroy(pp_);
    }

    BatchDetector(const BatchDetector&) = delete;
    BatchDetector& operator=(const BatchDetector&) = delete;

    void reset_tracker() {
        if (bt_) bt_reset(bt_);
    }

    // frames: numpy uint8 (B, H, W, 3) contiguous BGR
    // frame_idxs: length B
    // 戻り値: list[list[tuple(x1,y1,x2,y2,score,track_id)]]
    py::list detect_and_track(py::array frames, std::vector<int> frame_idxs) {
        // ── numpy 検証 ─────────────────────────────────────────────────
        if (!py::isinstance<py::array_t<uint8_t>>(frames)) {
            throw std::runtime_error("frames must be numpy uint8 array");
        }
        py::array_t<uint8_t, py::array::c_style | py::array::forcecast> arr(frames);
        if (arr.ndim() != 4) {
            throw std::runtime_error("frames must have shape (B, H, W, 3)");
        }
        const int B = static_cast<int>(arr.shape(0));
        const int H_src = static_cast<int>(arr.shape(1));
        const int W_src = static_cast<int>(arr.shape(2));
        const int C = static_cast<int>(arr.shape(3));
        if (C != 3) throw std::runtime_error("frames last dim must be 3 (BGR)");
        if (B == 0) return py::list();
        if (B > max_batch_) {
            throw std::runtime_error("batch B exceeds max_batch");
        }
        if (static_cast<int>(frame_idxs.size()) != B) {
            throw std::runtime_error("frame_idxs length must match B");
        }

        // ── frame pointer list を作る ─────────────────────────────────
        const uint8_t* base = arr.data();
        const size_t per_frame_bytes = static_cast<size_t>(H_src) * W_src * 3;
        std::vector<const uint8_t*> ptrs(B);
        for (int b = 0; b < B; ++b) {
            ptrs[b] = base + b * per_frame_bytes;
        }

        // ── preprocess + detector (GIL release) ───────────────────────
        // 出力 device buffer ptr / shape を保存
        void* d_out = nullptr;
        int n_ch = 0, n_anchors = 0;
        size_t out_elem = 0;
        {
            py::gil_scoped_release release;
            void* d_in = preprocess_run(pp_, ptrs.data(), B, H_src, W_src);
            DetOutput out = detector_infer(det_, d_in, B, h_dst_, w_dst_);
            if (out.B != B) {
                // GIL 取得直後に投げる
                py::gil_scoped_acquire acq;
                throw std::runtime_error("detector output batch mismatch");
            }
            d_out = out.dev_ptr;
            n_ch = out.n_ch;
            n_anchors = out.n_anchors;
            out_elem = static_cast<size_t>(detector_output_elem_size(det_));
        }

        if (n_ch != 5) {
            // 84-ch (COCO) は今は未対応。person だけの fine-tuned model 前提。
            throw std::runtime_error(
                "BatchDetector: expected n_ch=5 (1-class), got " + std::to_string(n_ch));
        }

        // ── device → host コピー (B * 5 * A * elem) ────────────────────
        const size_t total_elems = static_cast<size_t>(B) * n_ch * n_anchors;
        const size_t total_bytes = total_elems * out_elem;
        host_buf_.resize(total_bytes);
        {
            py::gil_scoped_release release;
            cudaError_t e = cudaMemcpy(host_buf_.data(), d_out, total_bytes,
                                       cudaMemcpyDeviceToHost);
            if (e != cudaSuccess) {
                py::gil_scoped_acquire acq;
                throw std::runtime_error(std::string("cudaMemcpy D2H failed: ") +
                                         cudaGetErrorString(e));
            }
        }

        // ── parse + ByteTracker (frame ごとに直列) ────────────────────
        // out layout: (B, n_ch=5, A) row-major
        //   per frame stride = n_ch * A
        //   ch=0:cx, 1:cy, 2:w, 3:h, 4:conf  (anchor index は最終次元)
        const float sx = static_cast<float>(W_src) / static_cast<float>(w_dst_);
        const float sy = static_cast<float>(H_src) / static_cast<float>(h_dst_);

        py::list results;
        std::vector<DetIn> dets;
        std::vector<TrackOut> tracks_out;
        dets.reserve(64);
        tracks_out.resize(256);

        for (int b = 0; b < B; ++b) {
            dets.clear();
            const size_t frame_offset_elems =
                static_cast<size_t>(b) * n_ch * n_anchors;

            // ch ごとの起点
            // (B, 5, A) なので ch=k の anchor i は offset = b*5*A + k*A + i
            auto read_val = [&](int ch, int anchor) -> float {
                size_t idx = frame_offset_elems +
                             static_cast<size_t>(ch) * n_anchors + anchor;
                if (out_elem == 2) {
                    const uint16_t* p = reinterpret_cast<const uint16_t*>(host_buf_.data());
                    return half_to_float(p[idx]);
                } else {
                    const float* p = reinterpret_cast<const float*>(host_buf_.data());
                    return p[idx];
                }
            };

            for (int a = 0; a < n_anchors; ++a) {
                float conf = read_val(4, a);
                if (conf < conf_thresh_) continue;
                float cx = read_val(0, a);
                float cy = read_val(1, a);
                float bw = read_val(2, a);
                float bh = read_val(3, a);

                // cxcywh → xyxy in input scale (W_dst, H_dst)
                float x1_in = cx - bw * 0.5f;
                float y1_in = cy - bh * 0.5f;
                float x2_in = cx + bw * 0.5f;
                float y2_in = cy + bh * 0.5f;
                // src scale に戻す
                float x1 = std::clamp(x1_in * sx, 0.0f, static_cast<float>(W_src));
                float y1 = std::clamp(y1_in * sy, 0.0f, static_cast<float>(H_src));
                float x2 = std::clamp(x2_in * sx, 0.0f, static_cast<float>(W_src));
                float y2 = std::clamp(y2_in * sy, 0.0f, static_cast<float>(H_src));
                if (x2 <= x1 || y2 <= y1) continue;
                dets.push_back(DetIn{x1, y1, x2, y2, conf});
            }

            // ByteTracker update
            int n_tracks = bt_update(bt_, dets.data(), static_cast<int>(dets.size()),
                                     frame_idxs[b],
                                     tracks_out.data(),
                                     static_cast<int>(tracks_out.size()));

            py::list frame_list;
            for (int t = 0; t < n_tracks; ++t) {
                const TrackOut& to = tracks_out[t];
                frame_list.append(py::make_tuple(
                    to.x1, to.y1, to.x2, to.y2, to.score, to.track_id));
            }
            results.append(std::move(frame_list));
        }

        return results;
    }

private:
    std::string onnx_path_;
    int max_batch_;
    bool use_fp16_;
    int h_dst_;
    int w_dst_;
    float conf_thresh_;

    PreprocessHandle* pp_ = nullptr;
    DetectorHandle* det_ = nullptr;
    ByteTrackerHandle* bt_ = nullptr;

    std::vector<uint8_t> host_buf_;  // device→host scratch
};

}  // namespace person_tracker_native

PYBIND11_MODULE(person_tracker_native_ext, m) {
    m.doc() = "person_tracker_native pybind11 module (Phase A3)";

    using person_tracker_native::BatchDetector;

    py::class_<BatchDetector>(m, "BatchDetector")
        .def(py::init<std::string, int, bool, bool, int, int, int, float>(),
             py::arg("onnx_path"),
             py::arg("max_batch") = 32,
             py::arg("use_fp16") = true,
             py::arg("use_trt") = true,
             py::arg("cuda_device") = 0,
             py::arg("h_dst") = 384,
             py::arg("w_dst") = 640,
             py::arg("conf_thresh") = 0.25f)
        .def("detect_and_track",
             &BatchDetector::detect_and_track,
             py::arg("frames"),
             py::arg("frame_idxs"),
             "Run preprocess+detect+ByteTrack for a batch of frames.\n"
             "frames: numpy uint8 (B, H, W, 3) BGR.\n"
             "frame_idxs: list[int] of length B.\n"
             "returns: list[list[(x1, y1, x2, y2, score, track_id)]].")
        .def("reset_tracker", &BatchDetector::reset_tracker,
             "Reset ByteTracker state (call between sets).");
}
