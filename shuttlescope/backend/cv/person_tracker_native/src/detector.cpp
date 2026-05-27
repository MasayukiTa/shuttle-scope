// detector.cpp — ORT C++ Session + IOBinding (TRT EP → CUDA EP fallback)
// Phase A1 (2026-05-27)
//
// 入力: device 側 (B, 3, H, W) fp16/fp32 (preprocess.cu の出力)
// 出力: device 側 (B, n_ch, n_anchors) ORT 管理バッファ (再呼び出しまで valid)
//
// 既存 Python 経路 (person_tracker.py) と同じく TRT EP を最優先、
// trt_engine_cache を backend/yolo/weights/trt_cache/ に流用する。

#include "detector.h"

#include <onnxruntime_cxx_api.h>
#include <cuda_runtime.h>

#include <string>
#include <vector>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <memory>

namespace person_tracker_native {

namespace {

#define CUDA_CHECK(expr) do { \
    cudaError_t _e = (expr); \
    if (_e != cudaSuccess) { \
        std::fprintf(stderr, "CUDA error %s at %s:%d : %s\n", \
                     #expr, __FILE__, __LINE__, cudaGetErrorString(_e)); \
        std::abort(); \
    } \
} while (0)

#ifdef _WIN32
std::wstring to_wstring_utf8(const char* s) {
    // ORT (Windows) は wchar_t の path を要求
    if (!s) return L"";
    size_t n = std::strlen(s);
    std::wstring w;
    w.reserve(n);
    // ASCII 仮定で十分 (model path 通常 ascii)。日本語 path 想定なら MultiByteToWideChar を使う。
    for (size_t i = 0; i < n; ++i) w.push_back(static_cast<wchar_t>(static_cast<unsigned char>(s[i])));
    return w;
}
#endif

}  // anonymous namespace

struct DetectorHandle {
    Ort::Env env{ORT_LOGGING_LEVEL_WARNING, "person_tracker_native"};
    std::unique_ptr<Ort::Session> session;
    Ort::MemoryInfo cuda_mem_info{nullptr};
    Ort::MemoryInfo cpu_mem_info{nullptr};
    Ort::AllocatorWithDefaultOptions allocator;

    int device_id = 0;
    bool fp16 = true;

    std::string input_name;
    std::string output_name;
    ONNXTensorElementDataType input_type = ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT16;
    ONNXTensorElementDataType output_type = ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT16;

    // 出力 device buffer (B, n_ch, n_anchors)。サイズが変わったら再確保。
    void* d_output = nullptr;
    size_t d_output_capacity = 0;
    int last_B = 0, last_n_ch = 0, last_n_anchors = 0;

    DetectorHandle() = default;
    ~DetectorHandle() {
        if (d_output) cudaFree(d_output);
    }
};

int detector_output_elem_size(const DetectorHandle* h) {
    return (h->output_type == ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT16) ? 2 : 4;
}

DetectorHandle* detector_create(const char* onnx_path,
                                int cuda_device,
                                bool use_trt,
                                bool fp16) {
    auto h = std::make_unique<DetectorHandle>();
    h->device_id = cuda_device;
    h->fp16 = fp16;

    Ort::SessionOptions so;
    so.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);

    bool trt_appended = false;
    if (use_trt) {
        // TensorRT EP: provider option を C API 経由で設定
        try {
            const OrtApi& api = Ort::GetApi();
            OrtTensorRTProviderOptionsV2* trt_opts = nullptr;
            Ort::ThrowOnError(api.CreateTensorRTProviderOptions(&trt_opts));

            // engine cache を Python 経路と同じ場所に流用
            std::string cache_path = std::string(onnx_path);
            auto sep = cache_path.find_last_of("/\\");
            if (sep != std::string::npos) cache_path = cache_path.substr(0, sep);
            cache_path += "/trt_cache_person_native";

            std::string dev_id = std::to_string(cuda_device);
            std::string fp16_flag = fp16 ? "1" : "0";
            const char* keys[] = {
                "device_id",
                "trt_fp16_enable",
                "trt_engine_cache_enable",
                "trt_engine_cache_path",
            };
            const char* vals[] = {
                dev_id.c_str(),
                fp16_flag.c_str(),
                "1",
                cache_path.c_str(),
            };
            Ort::ThrowOnError(api.UpdateTensorRTProviderOptions(trt_opts, keys, vals, 4));
            Ort::ThrowOnError(api.SessionOptionsAppendExecutionProvider_TensorRT_V2(
                static_cast<OrtSessionOptions*>(so), trt_opts));
            api.ReleaseTensorRTProviderOptions(trt_opts);
            trt_appended = true;
            std::fprintf(stderr, "[detector] TensorRT EP appended (cache=%s)\n", cache_path.c_str());
        } catch (const Ort::Exception& e) {
            std::fprintf(stderr, "[detector] TRT EP append failed: %s — fallback CUDA EP\n", e.what());
        }
    }

    // CUDA EP は TRT が成功 した場合 skip 可能 (env SS_PT_NATIVE_NO_CUDA_FALLBACK=1)。
    // Python から .pyd 経由で load する場合、CUDA EP は cuDNN を要求し、
    // torch の cudnn 9 と ORT 1.24 の cudnn 期待 ABI が衝突して fail することがある。
    // TRT-only で済む model (yolov8n 等) なら CUDA EP skip で安全。
    const char* no_cuda = std::getenv("SS_PT_NATIVE_NO_CUDA_FALLBACK");
    bool skip_cuda = (no_cuda && std::string(no_cuda) != "0") && trt_appended;
    if (!skip_cuda) {
        try {
            OrtCUDAProviderOptions cuda_opts{};
            cuda_opts.device_id = cuda_device;
            so.AppendExecutionProvider_CUDA(cuda_opts);
        } catch (const std::exception& e) {
            std::fprintf(stderr, "[detector] CUDA EP append failed (TRT will be sole EP): %s\n", e.what());
        }
    } else {
        std::fprintf(stderr, "[detector] CUDA EP skipped (TRT-only mode)\n");
    }

#ifdef _WIN32
    const auto wpath = to_wstring_utf8(onnx_path);
    h->session = std::make_unique<Ort::Session>(h->env, wpath.c_str(), so);
#else
    h->session = std::make_unique<Ort::Session>(h->env, onnx_path, so);
#endif

    h->cuda_mem_info = Ort::MemoryInfo("Cuda", OrtDeviceAllocator, cuda_device, OrtMemTypeDefault);
    h->cpu_mem_info  = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);

    // input/output 名取得
    {
        Ort::AllocatedStringPtr in_name = h->session->GetInputNameAllocated(0, h->allocator);
        Ort::AllocatedStringPtr out_name = h->session->GetOutputNameAllocated(0, h->allocator);
        h->input_name = in_name.get();
        h->output_name = out_name.get();

        auto in_type = h->session->GetInputTypeInfo(0).GetTensorTypeAndShapeInfo().GetElementType();
        auto out_type = h->session->GetOutputTypeInfo(0).GetTensorTypeAndShapeInfo().GetElementType();
        h->input_type = in_type;
        h->output_type = out_type;
        std::fprintf(stderr,
            "[detector] loaded: input=%s (dtype=%d), output=%s (dtype=%d), trt=%d\n",
            h->input_name.c_str(), (int)in_type,
            h->output_name.c_str(), (int)out_type,
            (int)trt_appended);
    }

    return h.release();
}

void detector_destroy(DetectorHandle* h) {
    delete h;
}

DetOutput detector_infer(DetectorHandle* h,
                         void* input_dev_ptr,
                         int B, int H, int W) {
    // 入力 shape: (B, 3, H, W)
    const int64_t in_shape[4] = {B, 3, H, W};
    const size_t in_elem = (h->input_type == ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT16) ? 2 : 4;
    const size_t in_bytes = (size_t)B * 3 * H * W * in_elem;

    Ort::Value input_tensor = Ort::Value::CreateTensor(
        h->cuda_mem_info, input_dev_ptr, in_bytes,
        in_shape, 4, h->input_type);

    Ort::IoBinding io(*h->session);
    io.BindInput(h->input_name.c_str(), input_tensor);

    // 出力は ORT に管理させる (device 上) → BindOutput(memory_info) 版
    io.BindOutput(h->output_name.c_str(), h->cuda_mem_info);

    Ort::RunOptions run_opts;
    h->session->Run(run_opts, io);

    // 出力テンソル取り出し (ORT 管理 buffer)
    std::vector<Ort::Value> outputs = io.GetOutputValues();
    if (outputs.empty()) {
        throw std::runtime_error("detector_infer: no outputs");
    }
    Ort::Value& out0 = outputs[0];
    auto info = out0.GetTensorTypeAndShapeInfo();
    auto shape = info.GetShape();  // expected (B, n_ch, n_anchors)
    if (shape.size() != 3) {
        throw std::runtime_error("detector_infer: expected 3D output");
    }

    DetOutput r;
    r.B = static_cast<int>(shape[0]);
    r.n_ch = static_cast<int>(shape[1]);
    r.n_anchors = static_cast<int>(shape[2]);

    // 注意: outputs ベクタを抜けると Ort::Value がデストラクトされ device buffer が解放される。
    // → 自前 buffer に device-to-device コピーして所有を移す。
    const size_t out_elem = (h->output_type == ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT16) ? 2 : 4;
    const size_t out_bytes = (size_t)r.B * r.n_ch * r.n_anchors * out_elem;
    if (out_bytes > h->d_output_capacity) {
        if (h->d_output) cudaFree(h->d_output);
        CUDA_CHECK(cudaMalloc(&h->d_output, out_bytes));
        h->d_output_capacity = out_bytes;
    }
    void* src_ptr = out0.GetTensorMutableRawData();
    CUDA_CHECK(cudaMemcpy(h->d_output, src_ptr, out_bytes, cudaMemcpyDeviceToDevice));

    h->last_B = r.B;
    h->last_n_ch = r.n_ch;
    h->last_n_anchors = r.n_anchors;
    r.dev_ptr = h->d_output;
    return r;
}

}  // namespace person_tracker_native
