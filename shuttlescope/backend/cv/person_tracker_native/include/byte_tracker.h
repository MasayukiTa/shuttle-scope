// ByteTracker C++ API (Phase A2)。
// Python backend/cv/byte_tracker.py の port。
// scratch MIT 実装、外部 tracker ライブラリ非依存。
#pragma once

#include <cstddef>

namespace person_tracker_native {

// 検出入力 (1 個分)
struct DetIn {
    float x1;
    float y1;
    float x2;
    float y2;
    float score;
};

// track 出力 (1 個分)
struct TrackOut {
    float x1;
    float y1;
    float x2;
    float y2;
    float score;
    int track_id;
    bool is_activated;
};

// opaque handle (前方宣言のみ、実体は cpp 内)
struct ByteTrackerHandle;

// tracker 生成。frame_rate / track_buffer は lost buffer 計算用、
// thresh_* は IoU マッチしきい値 (cost = 1 - iou)。
ByteTrackerHandle* bt_create(
    int frame_rate = 60,
    int track_buffer = 120,
    float thresh_high = 0.8f,
    float thresh_low = 0.5f,
    float thresh_unconfirmed = 0.7f);

// 1 フレーム update。tracked かつ is_activated な track のみ out_tracks に書く。
// 戻り値: 実際に書き込んだ track 数 (max_tracks まで)。
int bt_update(
    ByteTrackerHandle* h,
    const DetIn* dets,
    int n_dets,
    int frame_id,
    TrackOut* out_tracks,
    int max_tracks);

// 状態を完全リセット (set 切替え時など)
void bt_reset(ByteTrackerHandle* h);

// handle 破棄
void bt_destroy(ByteTrackerHandle* h);

}  // namespace person_tracker_native
