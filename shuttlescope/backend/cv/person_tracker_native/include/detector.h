// detector.h — ORT C++ Session ラッパ (TensorRT EP 優先、CUDA 直接 IOBinding)
// Phase A1 (2026-05-27)
#pragma once

#include <cstdint>

namespace person_tracker_native {

struct DetectorHandle;

// onnx_path: yolov8n_v2_finetuned_dyn.onnx 等
// cuda_device: GPU index
// use_trt: TensorrtExecutionProvider を試すか (失敗時は CUDA EP に fallback)
// fp16: 入力 fp16 を想定 (TRT FP16 enable も併せて on)
DetectorHandle* detector_create(const char* onnx_path,
                                int cuda_device,
                                bool use_trt,
                                bool fp16);

// 出力テンソル shape (B, n_ch, n_anchors)。
// dev_ptr は ORT が管理する GPU バッファ。次回 detector_infer 呼び出しまで valid。
struct DetOutput {
    int B;
    int n_ch;
    int n_anchors;
    void* dev_ptr;
};

// input_dev_ptr: preprocess_run の戻り値 (B, 3, H, W) fp16/fp32
DetOutput detector_infer(DetectorHandle* h,
                         void* input_dev_ptr,
                         int B, int H, int W);

// 出力 element サイズ (fp16=2, fp32=4)
int detector_output_elem_size(const DetectorHandle* h);

void detector_destroy(DetectorHandle* h);

}  // namespace person_tracker_native
