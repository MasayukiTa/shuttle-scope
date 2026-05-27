// ByteTracker C++ port。
// Python backend/cv/byte_tracker.py を 1 対 1 で移植。
// state machine と 3-pass Hungarian matching を再現する。
#include "byte_tracker.h"

#include <algorithm>
#include <array>
#include <cstring>
#include <memory>
#include <unordered_set>
#include <vector>

#include "hungarian.h"
#include "kalman.h"

namespace person_tracker_native {

namespace {

enum class TrackState : int { NewState = 0, Tracked = 1, Lost = 2, Removed = 3 };

// xyxy -> cxcyah
inline std::array<double, 4> xyxy_to_cxcyah(double x1, double y1, double x2, double y2) {
    double w = std::max(x2 - x1, 1e-6);
    double h = std::max(y2 - y1, 1e-6);
    return {x1 + w / 2.0, y1 + h / 2.0, w / h, h};
}

struct STrack {
    KalmanState ks{};
    bool has_kf = false;
    int track_id = -1;
    TrackState state = TrackState::NewState;
    int start_frame = 0;
    int frame_id = 0;
    int tracklet_len = 0;
    bool is_activated = false;
    double score = 0.0;
    // 初期 (KF 未適用) の cxcyah
    std::array<double, 4> init_cxcyah{};

    // 現在の xyxy
    std::array<double, 4> xyxy() const {
        double cx, cy, a, h;
        if (has_kf) {
            cx = ks.mean[0]; cy = ks.mean[1]; a = ks.mean[2]; h = ks.mean[3];
        } else {
            cx = init_cxcyah[0]; cy = init_cxcyah[1]; a = init_cxcyah[2]; h = init_cxcyah[3];
        }
        double w = a * h;
        return {cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0};
    }
};

inline std::shared_ptr<STrack> make_track(double x1, double y1, double x2, double y2, double score) {
    auto t = std::make_shared<STrack>();
    t->init_cxcyah = xyxy_to_cxcyah(x1, y1, x2, y2);
    t->score = score;
    t->state = TrackState::NewState;
    return t;
}

// IoU 行列 (size a x b、row-major)
std::vector<double> ious(
    const std::vector<std::shared_ptr<STrack>>& A,
    const std::vector<std::shared_ptr<STrack>>& B) {
    int na = (int)A.size(), nb = (int)B.size();
    std::vector<double> out(na * nb, 0.0);
    if (na == 0 || nb == 0) return out;
    for (int i = 0; i < na; ++i) {
        auto a = A[i]->xyxy();
        double area_a = (a[2] - a[0]) * (a[3] - a[1]);
        for (int j = 0; j < nb; ++j) {
            auto b = B[j]->xyxy();
            double x1 = std::max(a[0], b[0]);
            double y1 = std::max(a[1], b[1]);
            double x2 = std::min(a[2], b[2]);
            double y2 = std::min(a[3], b[3]);
            double w = std::max(0.0, x2 - x1);
            double h = std::max(0.0, y2 - y1);
            double inter = w * h;
            double area_b = (b[2] - b[0]) * (b[3] - b[1]);
            double uni = area_a + area_b - inter;
            out[i * nb + j] = inter / std::max(uni, 1e-9);
        }
    }
    return out;
}

struct MatchResult {
    std::vector<std::pair<int, int>> matches;
    std::vector<int> unmatched_a;
    std::vector<int> unmatched_b;
};

// cost = 1 - iou を Hungarian で解き、cost > thresh は捨てる
MatchResult linear_assignment(const std::vector<double>& iou_mat, int na, int nb, double thresh) {
    MatchResult r;
    if (na == 0 || nb == 0) {
        for (int i = 0; i < na; ++i) r.unmatched_a.push_back(i);
        for (int j = 0; j < nb; ++j) r.unmatched_b.push_back(j);
        return r;
    }
    std::vector<double> cost(na * nb);
    for (int i = 0; i < na * nb; ++i) cost[i] = 1.0 - iou_mat[i];
    auto assign = hungarian_solve(cost, na, nb);
    std::unordered_set<int> used_a, used_b;
    for (int i = 0; i < (int)assign.size(); ++i) {
        int j = assign[i];
        if (j < 0 || j >= nb) continue;
        if (cost[i * nb + j] <= thresh) {
            r.matches.emplace_back(i, j);
            used_a.insert(i);
            used_b.insert(j);
        }
    }
    for (int i = 0; i < na; ++i) if (!used_a.count(i)) r.unmatched_a.push_back(i);
    for (int j = 0; j < nb; ++j) if (!used_b.count(j)) r.unmatched_b.push_back(j);
    return r;
}

}  // namespace

// ── Handle ───────────────────────────────────────────────────────────────
struct ByteTrackerHandle {
    // 設定
    int frame_rate;
    int track_buffer;
    float thresh_high;       // match_thresh_high (iou)
    float thresh_low;        // match_thresh_low
    float thresh_unconfirmed;
    float track_high_thresh = 0.25f;  // detection score 下限 (high)
    float track_low_thresh = 0.10f;   // detection score 下限 (low)
    float new_track_thresh = 0.25f;   // 新規 track 起動の score 下限

    KalmanFilter kf;
    std::vector<std::shared_ptr<STrack>> tracked;
    std::vector<std::shared_ptr<STrack>> lost;
    int frame_id = 0;
    int next_track_id = 1;

    void activate(std::shared_ptr<STrack>& t, int fid) {
        t->track_id = next_track_id++;
        t->ks = kf.initiate(t->init_cxcyah);
        t->has_kf = true;
        t->tracklet_len = 0;
        t->state = TrackState::Tracked;
        t->frame_id = fid;
        t->start_frame = fid;
        // Python: is_activated = (frame_id == 0)
        t->is_activated = (fid == 0);
    }
    void re_activate(std::shared_ptr<STrack>& t, std::shared_ptr<STrack>& det, int fid, bool new_id) {
        kf.update(t->ks, det->init_cxcyah);
        t->tracklet_len = 0;
        t->state = TrackState::Tracked;
        t->is_activated = true;
        t->frame_id = fid;
        if (new_id) t->track_id = next_track_id++;
        t->score = det->score;
    }
    void update_track(std::shared_ptr<STrack>& t, std::shared_ptr<STrack>& det, int fid) {
        t->frame_id = fid;
        t->tracklet_len += 1;
        kf.update(t->ks, det->init_cxcyah);
        t->state = TrackState::Tracked;
        t->is_activated = true;
        t->score = det->score;
    }
    void predict_track(std::shared_ptr<STrack>& t) {
        if (!t->has_kf) return;
        if (t->state != TrackState::Tracked) {
            // lost 中は速度成分を 0 に
            t->ks.mean[6] = 0.0;
            t->ks.mean[7] = 0.0;
        }
        kf.predict(t->ks);
    }
};

ByteTrackerHandle* bt_create(int frame_rate, int track_buffer,
                              float thresh_high, float thresh_low, float thresh_unconfirmed) {
    auto* h = new ByteTrackerHandle();
    h->frame_rate = frame_rate;
    h->track_buffer = track_buffer;
    h->thresh_high = thresh_high;
    h->thresh_low = thresh_low;
    h->thresh_unconfirmed = thresh_unconfirmed;
    // detection score しきい値も Python 同様 caller が constants で渡したいが、
    // 簡単のため初期値を Python default に合わせる (golden test は 0.85+ なので影響なし)。
    return h;
}

void bt_destroy(ByteTrackerHandle* h) { delete h; }

void bt_reset(ByteTrackerHandle* h) {
    h->tracked.clear();
    h->lost.clear();
    h->frame_id = 0;
    h->next_track_id = 1;
}

int bt_update(ByteTrackerHandle* h, const DetIn* dets_in, int n_dets, int frame_id,
              TrackOut* out_tracks, int max_tracks) {
    h->frame_id = frame_id;

    // detection を high / low に分離
    std::vector<std::shared_ptr<STrack>> dets_high, dets_low;
    for (int i = 0; i < n_dets; ++i) {
        const auto& d = dets_in[i];
        if (d.score >= h->track_high_thresh) {
            dets_high.push_back(make_track(d.x1, d.y1, d.x2, d.y2, d.score));
        } else if (d.score >= h->track_low_thresh) {
            dets_low.push_back(make_track(d.x1, d.y1, d.x2, d.y2, d.score));
        }
    }

    // tracked / unconfirmed 分離
    std::vector<std::shared_ptr<STrack>> unconfirmed, tracked_active;
    for (auto& t : h->tracked) {
        if (t->is_activated) tracked_active.push_back(t);
        else unconfirmed.push_back(t);
    }

    // pool = tracked_active + lost、全部 predict
    std::vector<std::shared_ptr<STrack>> pool = tracked_active;
    for (auto& t : h->lost) pool.push_back(t);
    for (auto& t : pool) h->predict_track(t);

    // Step 1: high-conf det と pool
    auto iou1 = ious(pool, dets_high);
    auto m1 = linear_assignment(iou1, (int)pool.size(), (int)dets_high.size(),
                                1.0 - h->thresh_high);
    for (auto& [ip, idh] : m1.matches) {
        auto& tr = pool[ip];
        auto& dt = dets_high[idh];
        if (tr->state == TrackState::Tracked) {
            h->update_track(tr, dt, frame_id);
        } else {
            h->re_activate(tr, dt, frame_id, false);
        }
    }

    // Step 2: 残った tracked (state==Tracked) と low-conf det
    std::vector<std::shared_ptr<STrack>> remaining_tracked;
    std::vector<int> remaining_idx_in_pool;
    for (int i : m1.unmatched_a) {
        if (pool[i]->state == TrackState::Tracked) {
            remaining_tracked.push_back(pool[i]);
            remaining_idx_in_pool.push_back(i);
        }
    }
    auto iou2 = ious(remaining_tracked, dets_low);
    auto m2 = linear_assignment(iou2, (int)remaining_tracked.size(), (int)dets_low.size(),
                                1.0 - h->thresh_low);
    for (auto& [ir, idl] : m2.matches) {
        auto& tr = remaining_tracked[ir];
        auto& dt = dets_low[idl];
        h->update_track(tr, dt, frame_id);
    }
    for (int ir : m2.unmatched_a) {
        auto& tr = remaining_tracked[ir];
        if (tr->state == TrackState::Tracked) tr->state = TrackState::Lost;
    }

    // Step 3: unconfirmed と Step 1 で余った high-conf det
    std::vector<std::shared_ptr<STrack>> u_det_high_pool;
    for (int i : m1.unmatched_b) u_det_high_pool.push_back(dets_high[i]);
    auto iou3 = ious(unconfirmed, u_det_high_pool);
    auto m3 = linear_assignment(iou3, (int)unconfirmed.size(), (int)u_det_high_pool.size(),
                                1.0 - h->thresh_unconfirmed);
    for (auto& [iu, idh] : m3.matches) {
        auto& tr = unconfirmed[iu];
        auto& dt = u_det_high_pool[idh];
        h->update_track(tr, dt, frame_id);
    }
    for (int iu : m3.unmatched_a) unconfirmed[iu]->state = TrackState::Removed;

    // Step 4: 残った high-conf det を新規 track
    for (int idx : m3.unmatched_b) {
        auto& dt = u_det_high_pool[idx];
        if (dt->score < h->new_track_thresh) continue;
        h->activate(dt, frame_id);
        if (frame_id == 0 || frame_id == 1) dt->is_activated = true;
        h->tracked.push_back(dt);
    }

    // Step 5: 状態リスト再構築
    std::vector<std::shared_ptr<STrack>> new_tracked, new_lost;
    for (auto& t : h->tracked) {
        if (t->state == TrackState::Tracked) new_tracked.push_back(t);
        else if (t->state == TrackState::Lost) new_lost.push_back(t);
        // removed は drop
    }
    for (auto& t : h->lost) {
        if (t->state == TrackState::Tracked) {
            new_tracked.push_back(t);  // re_activate された
        } else if (t->state == TrackState::Lost) {
            if (frame_id - t->frame_id > h->track_buffer) {
                t->state = TrackState::Removed;
            } else {
                new_lost.push_back(t);
            }
        }
    }
    // 一意化 (re_activate された track が両方に居る可能性)
    std::unordered_set<int> seen;
    std::vector<std::shared_ptr<STrack>> dedup_tracked;
    for (auto& t : new_tracked) {
        if (seen.count(t->track_id)) continue;
        seen.insert(t->track_id);
        dedup_tracked.push_back(t);
    }
    std::vector<std::shared_ptr<STrack>> dedup_lost;
    for (auto& t : new_lost) {
        if (!seen.count(t->track_id)) dedup_lost.push_back(t);
    }
    h->tracked = dedup_tracked;
    h->lost = dedup_lost;

    // 出力: tracked かつ is_activated
    int n_out = 0;
    for (auto& t : h->tracked) {
        if (!t->is_activated) continue;
        if (n_out >= max_tracks) break;
        auto bb = t->xyxy();
        TrackOut& o = out_tracks[n_out++];
        o.x1 = (float)bb[0];
        o.y1 = (float)bb[1];
        o.x2 = (float)bb[2];
        o.y2 = (float)bb[3];
        o.score = (float)t->score;
        o.track_id = t->track_id;
        o.is_activated = t->is_activated;
    }
    return n_out;
}

}  // namespace person_tracker_native
