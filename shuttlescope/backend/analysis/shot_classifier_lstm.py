"""Model A — ショット種別分類器（LSTM + 位置シーケンス）

入力:
  シャトル xy + 打球選手 cx/cy/h × SEQ_LEN フレーム（打点中心）
  shape: (batch, SEQ_LEN, 5)  # [sx, sy, px, py, ph]

出力:
  18分類（CANONICAL_SHOTS） → 最大確率ラベル

学習スクリプト: train_shot_classifier_lstm.py（このモジュールと同ディレクトリ）
推論エントリ: ShotLSTMClassifier.predict()
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

from backend.analysis.shot_taxonomy import CANONICAL_SHOTS

logger = logging.getLogger(__name__)

SEQ_LEN = 40          # 打点前後 ±20 フレーム（60fps で約 0.67 秒）
INPUT_DIM = 5         # [shuttle_x, shuttle_y, player_cx, player_cy, player_h]
HIDDEN_DIM = 128
NUM_LAYERS = 2
NUM_CLASSES = len(CANONICAL_SHOTS)

# 保存先
WEIGHTS_DIR = Path(__file__).parent.parent / "models"
MODEL_PATH  = WEIGHTS_DIR / "shot_lstm.pt"
META_PATH   = WEIGHTS_DIR / "shot_lstm_meta.json"


# ─── ネットワーク定義 ─────────────────────────────────────────────────────────

def _build_model():
    """LSTM → Linear 分類ヘッド。PyTorch 未インストール時は None を返す。"""
    try:
        import torch
        import torch.nn as nn

        class ShotLSTM(nn.Module):
            def __init__(self):
                super().__init__()
                self.lstm = nn.LSTM(
                    input_size=INPUT_DIM,
                    hidden_size=HIDDEN_DIM,
                    num_layers=NUM_LAYERS,
                    batch_first=True,
                    dropout=0.3,
                )
                self.head = nn.Sequential(
                    nn.Linear(HIDDEN_DIM, 64),
                    nn.ReLU(),
                    nn.Dropout(0.2),
                    nn.Linear(64, NUM_CLASSES),
                )

            def forward(self, x):
                # x: (batch, seq, 5)
                out, _ = self.lstm(x)
                return self.head(out[:, -1, :])  # 最終フレームの隠れ状態

        return ShotLSTM()
    except ImportError:
        return None


# ─── 学習 ─────────────────────────────────────────────────────────────────────

def train(
    db_url: str,
    epochs: int = 50,
    batch_size: int = 64,
    lr: float = 1e-3,
    val_split: float = 0.15,
    device_str: str = "cpu",
) -> dict:
    """DB から学習データを構築し LSTM を学習する。

    必要テーブル:
      - strokes (stroke_id, shot_type, timestamp_sec)
      - shuttle_tracks (stroke_id, frame_index, x, y)
      - player_position_frames (stroke_id, frame_index, cx, cy, h)

    Returns: {"best_val_acc": float, "epochs": int, "model_path": str}
    """
    try:
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, TensorDataset, random_split
        import numpy as np
        from sqlalchemy import create_engine, text
    except ImportError as e:
        raise RuntimeError(f"学習に必要なパッケージがありません: {e}") from e

    from backend.analysis.shot_taxonomy import CANONICAL_SHOTS, canonicalize

    engine = create_engine(db_url)
    label_idx = {s: i for i, s in enumerate(CANONICAL_SHOTS)}

    logger.info("ShotLSTM: 学習データをDBから取得中...")
    with engine.connect() as conn:
        strokes = conn.execute(text(
            "SELECT id, shot_type, timestamp_sec FROM strokes "
            "WHERE shot_type IS NOT NULL AND shot_type != ''"
        )).fetchall()

        shuttle_rows = conn.execute(text(
            "SELECT stroke_id, frame_index, x, y FROM shuttle_tracks ORDER BY stroke_id, frame_index"
        )).fetchall()

        player_rows = conn.execute(text(
            "SELECT stroke_id, frame_index, cx, cy, h FROM player_position_frames ORDER BY stroke_id, frame_index"
        )).fetchall()

    # フレームマップ構築
    shuttle_map: dict[int, list] = {}
    for row in shuttle_rows:
        shuttle_map.setdefault(row.stroke_id, []).append((row.frame_index, row.x, row.y))

    player_map: dict[int, list] = {}
    for row in player_rows:
        player_map.setdefault(row.stroke_id, []).append((row.frame_index, row.cx, row.cy, row.h))

    # シーケンス構築
    X_list, y_list = [], []
    skipped = 0
    for stroke in strokes:
        sid = stroke.id
        label = canonicalize(stroke.shot_type or "")
        if label not in label_idx:
            skipped += 1
            continue

        sht = sorted(shuttle_map.get(sid, []), key=lambda r: r[0])
        pla = sorted(player_map.get(sid, []), key=lambda r: r[0])
        if len(sht) < 4 or len(pla) < 4:
            skipped += 1
            continue

        # 打点周辺 SEQ_LEN フレームを選択・補間してベクトル化
        sht_dict = {r[0]: (r[1], r[2]) for r in sht}
        pla_dict = {r[0]: (r[1], r[2], r[3]) for r in pla}
        all_frames = sorted(set(sht_dict) | set(pla_dict))

        # リサンプル: SEQ_LEN 等間隔でサンプル
        indices = np.linspace(0, len(all_frames) - 1, SEQ_LEN, dtype=int)
        seq = []
        for idx in indices:
            fi = all_frames[idx]
            sx, sy = sht_dict.get(fi, (0.0, 0.0))
            px, py, ph = pla_dict.get(fi, (0.5, 0.5, 0.2))
            seq.append([sx, sy, px, py, ph])
        X_list.append(seq)
        y_list.append(label_idx[label])

    if len(X_list) < 20:
        raise RuntimeError(
            f"学習サンプル数が少なすぎます（{len(X_list)} 件）。"
            "シャトルトラック・選手座標・ストロークデータを確認してください。"
        )
    logger.info(
        "ShotLSTM: %d サンプル（skip=%d）, クラス分布=%s",
        len(X_list), skipped,
        {CANONICAL_SHOTS[i]: int(np.sum(np.array(y_list) == i)) for i in range(NUM_CLASSES) if int(np.sum(np.array(y_list) == i)) > 0},
    )

    X = torch.tensor(X_list, dtype=torch.float32)
    y = torch.tensor(y_list, dtype=torch.long)

    dataset = TensorDataset(X, y)
    val_size = max(1, int(len(dataset) * val_split))
    train_size = len(dataset) - val_size
    train_ds, val_ds = random_split(dataset, [train_size, val_size])

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
    val_loader   = DataLoader(val_ds, batch_size=batch_size)

    device = torch.device(device_str)
    model = _build_model().to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    criterion = nn.CrossEntropyLoss()
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=5, factor=0.5)

    best_val_acc = 0.0
    best_state = None

    for epoch in range(epochs):
        model.train()
        train_loss = 0.0
        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            optimizer.zero_grad()
            loss = criterion(model(xb), yb)
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * len(xb)

        # 検証
        model.eval()
        correct = total = 0
        with torch.no_grad():
            for xb, yb in val_loader:
                xb, yb = xb.to(device), yb.to(device)
                preds = model(xb).argmax(dim=1)
                correct += (preds == yb).sum().item()
                total += len(yb)
        val_acc = correct / total if total > 0 else 0.0
        scheduler.step(1 - val_acc)

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

        if (epoch + 1) % 10 == 0:
            logger.info(
                "ShotLSTM epoch %d/%d  train_loss=%.4f  val_acc=%.3f",
                epoch + 1, epochs, train_loss / train_size, val_acc,
            )

    # 保存
    WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    if best_state:
        model.load_state_dict(best_state)
    torch.save(model.state_dict(), MODEL_PATH)
    meta = {
        "best_val_acc": round(best_val_acc, 4),
        "epochs": epochs,
        "seq_len": SEQ_LEN,
        "classes": CANONICAL_SHOTS,
        "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "samples": len(X_list),
    }
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("ShotLSTM: 保存完了 val_acc=%.3f → %s", best_val_acc, MODEL_PATH)
    return {"best_val_acc": best_val_acc, "epochs": epochs, "model_path": str(MODEL_PATH)}


# ─── 推論 ─────────────────────────────────────────────────────────────────────

class ShotLSTMClassifier:
    """学習済み LSTM モデルで shot_type を推論するシングルトンラッパー。"""

    def __init__(self) -> None:
        self._model = None
        self._loaded = False
        self._device = "cpu"

    def load(self) -> bool:
        if self._loaded:
            return True
        if not MODEL_PATH.exists():
            logger.warning("ShotLSTM: 重みが見つかりません (%s) — train() を先に実行してください", MODEL_PATH)
            return False
        try:
            import torch
            m = _build_model()
            if m is None:
                return False
            state = torch.load(MODEL_PATH, map_location="cpu", weights_only=True)
            m.load_state_dict(state)
            m.eval()
            self._model = m
            self._loaded = True
            logger.info("ShotLSTM: ロード完了 (%s)", MODEL_PATH)
            return True
        except Exception as exc:
            logger.warning("ShotLSTM: ロード失敗 %s", exc)
            return False

    def predict(
        self,
        shuttle_xy: list[tuple[float, float]],
        player_cxyh: list[tuple[float, float, float]],
    ) -> Optional[dict]:
        """シャトル座標列・選手座標列から shot_type を予測する。

        Args:
            shuttle_xy: [(x, y), ...] — 正規化座標 (0-1)
            player_cxyh: [(cx, cy, h), ...] — 正規化座標 (0-1)

        Returns:
            {"shot_type": str, "confidence": float, "top3": [...]} or None
        """
        if not self.load():
            return None
        try:
            import torch
            import numpy as np

            n_frames = max(len(shuttle_xy), len(player_cxyh))
            if n_frames < 4:
                return None

            indices = np.linspace(0, n_frames - 1, SEQ_LEN, dtype=int)
            sxy = list(shuttle_xy) + [(0.0, 0.0)] * (n_frames - len(shuttle_xy))
            pcxyh = list(player_cxyh) + [(0.5, 0.5, 0.2)] * (n_frames - len(player_cxyh))

            seq = []
            for i in indices:
                sx, sy = sxy[min(i, len(sxy) - 1)]
                px, py, ph = pcxyh[min(i, len(pcxyh) - 1)]
                seq.append([sx, sy, px, py, ph])

            x = torch.tensor([seq], dtype=torch.float32)
            with torch.no_grad():
                logits = self._model(x)[0]
                probs = torch.softmax(logits, dim=0)

            top3 = sorted(
                [(CANONICAL_SHOTS[i], float(probs[i])) for i in range(NUM_CLASSES)],
                key=lambda p: p[1], reverse=True,
            )[:3]
            return {
                "shot_type": top3[0][0],
                "confidence": round(top3[0][1], 3),
                "top3": [{"shot_type": s, "prob": round(p, 3)} for s, p in top3],
            }
        except Exception as exc:
            logger.warning("ShotLSTM predict error: %s", exc)
            return None

    def get_meta(self) -> Optional[dict]:
        """学習メタ情報（val_acc, 学習日時など）を返す。"""
        if not META_PATH.exists():
            return None
        try:
            return json.loads(META_PATH.read_text(encoding="utf-8"))
        except Exception:
            return None


_lstm_instance: Optional[ShotLSTMClassifier] = None


def get_shot_lstm() -> ShotLSTMClassifier:
    global _lstm_instance
    if _lstm_instance is None:
        _lstm_instance = ShotLSTMClassifier()
    return _lstm_instance
