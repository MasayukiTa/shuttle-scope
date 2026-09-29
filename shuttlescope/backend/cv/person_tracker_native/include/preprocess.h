// preprocess.h — CUDA preprocess API (uint8 BGR → fp16/fp32 RGB NCHW normalized)
// Phase A1 (2026-05-27)
#pragma once

#include <cstdint>
#include <cstddef>

namespace person_tracker_native {

struct PreprocessHandle;

// max_batch: 最大バッチ (内部 GPU バッファ確保用)
// H_dst/W_dst: 推論モデル入力解像度 (例: 384x640)
// fp16: 出力 fp16 (true) or fp32 (false)
PreprocessHandle* preprocess_create(int max_batch, int H_dst, int W_dst, bool fp16);

// frames: host 側 uint8 BGR HWC ポインタ列 (長さ B、各 H_src*W_src*3 bytes)
// 戻り値: device 側 (B, 3, H_dst, W_dst) RGB normalized tensor の生 GPU ポインタ。
//         呼び出し側は preprocess_destroy までは valid と仮定して使える。
// 注: stream は内部の cudaStream、preprocess_run 終了時に synchronize 済み。
void* preprocess_run(PreprocessHandle* h, const uint8_t** frames,
                     int B, int H_src, int W_src);

// 出力 element サイズ (fp16=2, fp32=4) を返す。検証/サイズ計算用。
size_t preprocess_elem_size(const PreprocessHandle* h);

void preprocess_destroy(PreprocessHandle* h);

}  // namespace person_tracker_native
