// preprocess.cu — uint8 BGR HWC → fp16/fp32 RGB NCHW resize+normalize 1-kernel
// Phase A1 (2026-05-27)
//
// 入力: (B, H_src, W_src, 3) uint8 BGR (連続 host memory)
// 出力: (B, 3, H_dst, W_dst) fp16 or fp32 RGB / 255.0, bilinear resize
//
// torch.interpolate(BGR→RGB→/255) 相当を 1 カーネルで完結させ、
// host→device コピーも内部で吸収する。

#include "preprocess.h"

#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>

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

template <typename T>
__device__ inline T from_float(float v);

template <>
__device__ inline __half from_float<__half>(float v) { return __float2half(v); }

template <>
__device__ inline float from_float<float>(float v) { return v; }

template <typename T>
__global__ void preprocess_kernel(
    const uint8_t* __restrict__ input,  // (B, H_src, W_src, 3) BGR
    T* __restrict__ output,             // (B, 3, H_dst, W_dst) RGB normalized
    int B, int H_src, int W_src,
    int H_dst, int W_dst,
    float scale_y, float scale_x       // = H_src / H_dst, W_src / W_dst
) {
    const int x = blockIdx.x * blockDim.x + threadIdx.x;
    const int y = blockIdx.y * blockDim.y + threadIdx.y;
    const int b = blockIdx.z;
    if (x >= W_dst || y >= H_dst || b >= B) return;

    // bilinear sample (align_corners=False, torch interpolate と同じ)
    // src_pos = (dst_pos + 0.5) * scale - 0.5
    float fx = (x + 0.5f) * scale_x - 0.5f;
    float fy = (y + 0.5f) * scale_y - 0.5f;
    if (fx < 0) fx = 0; if (fy < 0) fy = 0;
    if (fx > W_src - 1) fx = W_src - 1;
    if (fy > H_src - 1) fy = H_src - 1;

    const int x0 = static_cast<int>(fx);
    const int y0 = static_cast<int>(fy);
    const int x1 = min(x0 + 1, W_src - 1);
    const int y1 = min(y0 + 1, H_src - 1);
    const float wx = fx - x0;
    const float wy = fy - y0;

    const uint8_t* base = input + (size_t)b * H_src * W_src * 3;

    auto sample = [&](int px, int py, int ch) -> float {
        return static_cast<float>(base[(py * W_src + px) * 3 + ch]);
    };

    // BGR HWC → RGB ch ordering: out_ch=0 (R) は src ch=2、out_ch=2 (B) は src ch=0
    const int bgr_for_rgb[3] = {2, 1, 0};

    const size_t plane = (size_t)H_dst * W_dst;
    T* out_base = output + (size_t)b * 3 * plane;

    #pragma unroll
    for (int ch = 0; ch < 3; ++ch) {
        const int src_ch = bgr_for_rgb[ch];
        const float v00 = sample(x0, y0, src_ch);
        const float v01 = sample(x1, y0, src_ch);
        const float v10 = sample(x0, y1, src_ch);
        const float v11 = sample(x1, y1, src_ch);
        const float v0 = v00 * (1.0f - wx) + v01 * wx;
        const float v1 = v10 * (1.0f - wx) + v11 * wx;
        const float v  = v0  * (1.0f - wy) + v1  * wy;
        const float norm = v * (1.0f / 255.0f);
        out_base[ch * plane + y * W_dst + x] = from_float<T>(norm);
    }
}

}  // anonymous namespace

struct PreprocessHandle {
    int max_batch;
    int H_dst, W_dst;
    bool fp16;
    cudaStream_t stream;
    // device 側 buffer (使い回し)
    uint8_t* d_input = nullptr;        // (max_batch, H_src_max, W_src_max, 3)
    void*    d_output = nullptr;       // (max_batch, 3, H_dst, W_dst)
    size_t   d_input_capacity = 0;     // bytes
    size_t   d_output_capacity = 0;    // bytes
};

size_t preprocess_elem_size(const PreprocessHandle* h) {
    return h->fp16 ? sizeof(__half) : sizeof(float);
}

PreprocessHandle* preprocess_create(int max_batch, int H_dst, int W_dst, bool fp16) {
    auto* h = new PreprocessHandle();
    h->max_batch = max_batch;
    h->H_dst = H_dst;
    h->W_dst = W_dst;
    h->fp16 = fp16;
    CUDA_CHECK(cudaStreamCreate(&h->stream));

    // output buffer は形状固定なので前もって確保
    const size_t out_bytes = (size_t)max_batch * 3 * H_dst * W_dst * preprocess_elem_size(h);
    CUDA_CHECK(cudaMalloc(&h->d_output, out_bytes));
    h->d_output_capacity = out_bytes;

    return h;
}

void preprocess_destroy(PreprocessHandle* h) {
    if (!h) return;
    if (h->d_input) cudaFree(h->d_input);
    if (h->d_output) cudaFree(h->d_output);
    if (h->stream) cudaStreamDestroy(h->stream);
    delete h;
}

void* preprocess_run(PreprocessHandle* h, const uint8_t** frames,
                     int B, int H_src, int W_src) {
    if (B <= 0) return h->d_output;
    if (B > h->max_batch) {
        std::fprintf(stderr, "preprocess_run: B=%d > max_batch=%d\n", B, h->max_batch);
        std::abort();
    }

    const size_t per_frame_bytes = (size_t)H_src * W_src * 3;
    const size_t need_bytes = per_frame_bytes * B;
    if (need_bytes > h->d_input_capacity) {
        if (h->d_input) cudaFree(h->d_input);
        CUDA_CHECK(cudaMalloc(&h->d_input, need_bytes));
        h->d_input_capacity = need_bytes;
    }

    // host frames を pinned 経由 ... ここでは単純に cudaMemcpyAsync (pageable) で OK
    // (将来: pinned staging buffer を導入で更に高速化可)
    for (int b = 0; b < B; ++b) {
        CUDA_CHECK(cudaMemcpyAsync(
            h->d_input + (size_t)b * per_frame_bytes,
            frames[b], per_frame_bytes, cudaMemcpyHostToDevice, h->stream));
    }

    dim3 block(16, 16, 1);
    dim3 grid((h->W_dst + block.x - 1) / block.x,
              (h->H_dst + block.y - 1) / block.y,
              B);

    const float scale_y = static_cast<float>(H_src) / h->H_dst;
    const float scale_x = static_cast<float>(W_src) / h->W_dst;

    if (h->fp16) {
        preprocess_kernel<__half><<<grid, block, 0, h->stream>>>(
            h->d_input, reinterpret_cast<__half*>(h->d_output),
            B, H_src, W_src, h->H_dst, h->W_dst, scale_y, scale_x);
    } else {
        preprocess_kernel<float><<<grid, block, 0, h->stream>>>(
            h->d_input, reinterpret_cast<float*>(h->d_output),
            B, H_src, W_src, h->H_dst, h->W_dst, scale_y, scale_x);
    }
    CUDA_CHECK(cudaGetLastError());
    CUDA_CHECK(cudaStreamSynchronize(h->stream));
    return h->d_output;
}

}  // namespace person_tracker_native
