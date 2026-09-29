# PersonTracker Native Runtime — Phase A1 (preprocess + ORT detector)

日付: 2026-05-27
ブランチ: `feat/person-tracker-phase1-2`
スコープ: `shuttlescope/backend/cv/person_tracker_native/` の A1 担当範囲

## 変更内容

CUDA preprocess kernel と ORT C++ inference engine を新規実装した。
Phase A2 (ByteTracker port) と並行で進行する subagent 構造のため、
A2 が同時に追加する `byte_tracker.{h,cpp}` / `kalman.{h,cpp}` /
`hungarian.{h,cpp}` を CMake が optional に拾う build script を組んだ。

### 追加ファイル (A1 担当)

- `CMakeLists.txt` — CUDA + ORT 1.24.4 + 任意 pybind11 を find する。
  A2 の追加 source は `EXISTS` チェックで optional リンク。
- `include/preprocess.h` — CUDA preprocess の C API 宣言。
- `include/detector.h` — ORT 推論ラッパの C API 宣言 + `DetOutput` struct。
- `src/preprocess.cu` — uint8 BGR HWC → fp16/fp32 RGB NCHW resize+normalize
  を 1 kernel で完結。bilinear (align_corners=False, torch interpolate 互換)。
- `src/detector.cpp` — `Ort::Session` + `Ort::IoBinding` で device tensor
  直接渡し。TensorRT EP 最優先 (fp16 + engine cache `trt_cache_person_native`)、
  失敗時は CUDA EP に自動 fallback。出力は ORT 管理 buffer → 自前 device
  buffer に D2D コピーして lifetime を呼び出し側で安全化。
- `src/detector_test.cpp` — 1920×1080 dummy frames (B=4) を 384×640 にリサイズ
  → 推論 → shape 検証 + 50 iter ベンチで fps を表示する単体テスト。
- `setup.py` — `pip install -e .` で cmake を driven する pybind11 build
  skaffold (A3 の `bindings.cpp` が来たら .pyd を生成する)。

### A1 公開 API

```cpp
PreprocessHandle* preprocess_create(int max_batch, int H_dst, int W_dst, bool fp16);
void* preprocess_run(PreprocessHandle*, const uint8_t** frames,
                     int B, int H_src, int W_src);
void preprocess_destroy(PreprocessHandle*);

DetectorHandle* detector_create(const char* onnx_path, int cuda_device,
                                bool use_trt, bool fp16);
DetOutput detector_infer(DetectorHandle*, void* input_dev_ptr, int B, int H, int W);
void detector_destroy(DetectorHandle*);
```

`preprocess_run` の返す GPU pointer をそのまま `detector_infer` に渡せる。
Host↔Device copy は preprocess 段の H2D 1 回だけ、それ以降 inference 完了まで
GPU 上を一度も離れない。

## 既存コードとの関係

- `backend/cv/person_tracker.py` の Python 経路は **無修正**。
  既存の `update_batch` (Python + torch.interpolate + ORT IObinding) はそのまま残る。
- TRT engine cache は別 path (`trt_cache_person_native`) を使用。
  既存 cache (`trt_cache_person_batch`) を壊さない。
- onnx model 解決ロジックは A3 binding 側で env (`SS_PERSON_TRACKER_BATCH_MODEL`)
  経由とする予定。A1 の `detector_test.cpp` は単独 exe として
  `argv[1]` または既知の相対 path から探す簡易版を持つ。

## ビルド (本番ホスト)

```
cd shuttlescope/backend/cv/person_tracker_native
mkdir build && cd build
cmake .. -G "Visual Studio 17 2022" -A x64 ^
  -DORT_ROOT="C:/onnxruntime/onnxruntime-win-x64-gpu-1.24.4"
cmake --build . --config Release
.\Release\detector_test.exe
```

期待出力 (warmup 後 50 iter bench):

```
[detector] TensorRT EP appended (cache=...)
[detector] loaded: input=images (dtype=10), output=output0 (dtype=10), trt=1
[test] preprocess done, d_in=0x..., elem=2
[test] infer warm: B=4 n_ch=5 n_anchors=5040 dev_ptr=0x...
[test] bench: N=50 B=4 total=... ms => ... fps
OK B=4 n_ch=5 n_anchors=5040 fps=...
```

## ローカル build 検証ステータス

**未実施 (理由: 開発機 (M118A8586) に CUDA toolkit と ORT C++ SDK の install が無い)**。
本タスクは subagent (auto mode) で実行されたため本番ホスト (ssh shuttle-scope)
への build 実行は権限上保留した。**本番ホストで上記 cmake 手順を 1 度実行して
detector_test.exe の OK 出力を確認する必要がある**。コンパイル時の文法 / link
問題が出た場合の対応点:

1. ORT C++ API の dtype enum 値 (`ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT16=10`) は
   1.24.4 想定。
2. `OrtCUDAProviderOptions` 構造体は ORT 1.24 系で stable。
3. CUDA arch `120` (Blackwell, 5060 Ti) は CUDA 12.8 toolkit が必要。

## 残課題 (A3 への申し送り)

- `src/bindings.cpp` を A3 で追加。pybind11 module 名 = `person_tracker_native_ext`
  (CMakeLists で予約済)。
- Python wrapper `update_batch_native(frames, idxs)` を
  `backend/cv/person_tracker.py` に追加。env `SS_PERSON_TRACKER_USE_NATIVE` で
  既存 `update_batch` への fallback 制御。
- A1 の `detector_infer` 出力は **device 上 (B, n_ch, n_anchors)**。
  bbox parse (conf threshold + xywh→xyxy + 1080p 座標復元) は A3 binding 側で
  thrust or cuBLAS で実装するか、host にコピーしてから python/CPU で処理するか
  決める。Python 経路の `_parse_outputs_vectorized` が既存ロジックの reference。
- A2 の `bt_update` 出力 (TrackOut[]) を bindings 層で `(x1, y1, x2, y2, conf, id)`
  tuple に詰めて Python に返す。

## interface 仕様 補足

- `DetOutput.dev_ptr` の lifetime: **次回 `detector_infer` 呼び出しまで** valid。
  binding 層で同一 frame 内に bbox parse まで終わらせるか、別 device buffer に
  退避すること。
- `preprocess_run` の戻り device pointer も同様に **次回 `preprocess_run` まで** valid。
- `preprocess_create` の `max_batch` を超える B を渡すと `std::abort()`。
  binding 層で max_batch を sticky に保つこと。
