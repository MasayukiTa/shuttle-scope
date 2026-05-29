# Native detector integration into PersonTracker batch path — 2026-05-29

## 目的
working な C++ native detector (`person_tracker_native_ext.pyd`,
YOLOv8n 1-class / ONNX Runtime + TensorRT FP16 EP) を Python の
`PersonTracker` batch 経路に **opt-in** で組み込む。既定は完全に従来どおりの
Python ONNX 経路で、ゼロ behavior change。

対象ファイル: `shuttlescope/backend/cv/person_tracker.py`

## 何を配線したか
- `update_batch()` を **dispatcher** 化:
  - `SS_PERSON_USE_NATIVE` 未設定 (既定) → `_update_batch_python()`
    (= 従来の Python ONNX session 経路。挙動不変)。
  - `SS_PERSON_USE_NATIVE=1` → `update_batch_native()` を試す。
- `update_batch_native()` は C++ `BatchDetector.detect_and_track()` に
  (B,H,W,3) uint8 BGR をまとめて渡し、戻り値
  `[(x1,y1,x2,y2,score,track_id)]` を **そのまま `TrackedPerson`** に map。
  native 側は preprocess(CUDA)+detect(ORT/TRT)+ByteTrack を一気通貫で実行。
  Python 側は **court adjudication と player_label 付与のみ** を従来関数
  (`adjudicate_court` / `_attach_player_label`) で実施 → 下流の court
  裁定・labeling は一切変更なし。
- `_ensure_native_detector()` が `BatchDetector(model, batch=32, use_trt,
  use_cuda=True, device_id=0, in_h, in_w, conf)` を positional で構築
  (実 .pyd の binding シグネチャに一致)。
- `_load_native_ext()` が `person_tracker_native_ext` を遅延 import。
  import 前に `test_native_import.py` と同じ順序で DLL 探索 dir を追加:
  ORT lib → CUDA bin → TensorRT bin → build/Release。torch を先に import
  して prod の load 順序を再現。

## 追加した環境変数
| env | 既定 | 用途 |
|-----|------|------|
| `SS_PERSON_USE_NATIVE` | `0` (OFF) | native fast path の opt-in スイッチ |
| `SS_PT_MODEL` | (batch model env → default) | native が使う ONNX model path |
| `SS_NATIVE_ORT_LIB` | `C:/onnxruntime/onnxruntime-win-x64-gpu-1.24.4/lib` | ORT DLL 探索 dir |
| `SS_NATIVE_CUDA_BIN` | `C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v12.8/bin` | CUDA runtime DLL |
| `SS_NATIVE_TRT_BIN` | `C:/TensorRT/TensorRT-10.16.1.11/bin` | TensorRT DLL |
| `SS_NATIVE_PYD_DIR` | `<cv>/person_tracker_native/build/Release` | .pyd 本体 dir |
| `SS_NATIVE_IN_H` / `SS_NATIVE_IN_W` | `384` / `640` | native 入力解像度 |
| `SS_PT_NATIVE_NO_TRT` | `0` | `1` で TRT EP を無効化 (CUDA EP) |

prod path は env で上書き可能 (hardcode しない)。

## Fallback 挙動 (critical)
native が **どんな理由でも** 使えない場合は warning を log して Python core
(`_update_batch_python`) に fallback。app は決して crash しない。fallback する
ケース:
1. `SS_PERSON_USE_NATIVE` 未設定 → そもそも native を触らない。
2. `.pyd` / DLL の import 失敗 (`_load_native_ext()` が None)。
3. `BatchDetector` 構築失敗 (model 不在 / session 作成失敗など)。
4. 実行時に `detect_and_track()` が例外。
5. frame 形状が不揃い (native は同一形状 batch 前提)。
import の試行は module 級に 1 度だけ cache (失敗を記憶し再試行しない)。

## テスト
`shuttlescope/backend/tests/test_native_detector.py` (3 件、**.pyd 不要 / GPU
不要** で pass):
- `test_default_uses_python_path` — env 未設定で native を一切触らず Python
  core のみ呼ぶ。
- `test_native_import_failure_falls_back` — `SS_PERSON_USE_NATIVE=1` でも
  `_load_native_ext` が None を返したら Python core に graceful fallback、
  crash しない。
- `test_loader_swallows_import_error` — `__import__` を mock して
  `person_tracker_native_ext` の import を raise させても `_load_native_ext`
  は None を返し例外を伝播しない (+ cache で再 import しない)。

結果: `3 passed`。既存 `test_person_tracker.py` も `32 passed` (回帰なし)。

## Prod smoke (GPU, native path)
- 環境: `SS_PERSON_USE_NATIVE=1`, `SS_PT_MODEL` = live
  `yolov8n_v2_finetuned_dyn.onnx`。B=8、1920x1080、30 iter。
- 結果: **fps=301.2** (240 frames = B8 x 30 iter)。`native_detector is None?
  False` → native TensorRT 経路が実際に GPU 上で実行された。
- random noise frame のため検出 0 (人物が写っていないので当然) だが、
  native → TrackedPerson → court adjudication の一気通貫が crash せず正常
  動作することを確認。standalone harness の生 fps (~632) に対し、ここでは
  Python 側の np.stack + per-frame court 裁定 + dispatch overhead 込みで 301 fps。
- 既存 Python batch 経路と同じ `update_batch(frames, frame_idxs)` API で透過的に
  native に切り替わる (env のみで制御)。

## 配線したファイル / commit
- `shuttlescope/backend/cv/person_tracker.py` (+113 / -37)
  - 旧 eager `_ext` import (DLL dir 設定なし) を削除し、DLL 探索 dir を
    test_native_import.py と同じ順序で張る `_load_native_ext()` に置換。
  - `update_batch` を dispatcher 化、Python core を `_update_batch_python` に。
  - `_ensure_native_detector` を実 .pyd の positional ctor に合わせて修正。
- `shuttlescope/backend/tests/test_native_detector.py` (新規, 3 tests)
- `shuttlescope/docs/validation/native-detector-integration-2026-05-29.md` (本書)

## 制約遵守
- worktree `wt-cpp-integ` / branch `feat/person-tracker-phase1-2` のみで作業。
- model file は commit しない (env / 既存 live checkout 参照)。
- docs/ は gitignore のため `git add -f`。
