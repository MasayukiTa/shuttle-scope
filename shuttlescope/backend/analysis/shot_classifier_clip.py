"""Model B — ショット種別分類器（動画クリップ + MobileNetV3 + LSTM）

入力:
  打点前後 ±HALF_CLIP フレームの動画クリップ
  MobileNetV3-Small で各フレームを特徴抽出（576次元）→ LSTM で時系列集約

出力:
  18分類（CANONICAL_SHOTS） → 最大確率ラベル

学習スクリプト: train_shot_classifier_clip.py（このモジュールと同ディレクトリ）
推論エントリ: ShotClipClassifier.predict_frames()
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

from backend.analysis.shot_taxonomy import CANONICAL_SHOTS

logger = logging.getLogger(__name__)

HALF_CLIP  = 30          # 打点前後 30 フレーム（合計 61 フレーム）
FRAME_SIZE = (112, 112)  # MobileNetV3 への入力サイズ
FEAT_DIM   = 576         # MobileNetV3-Small の出力次元
HIDDEN_DIM = 256
NUM_LAYERS = 2
NUM_CLASSES = len(CANONICAL_SHOTS)
SAMPLE_FRAMES = 20       # 推論時に等間隔でサンプルするフレーム数（全フレームは重い）

WEIGHTS_DIR  = Path(__file__).parent.parent / "models"
MODEL_PATH   = WEIGHTS_DIR / "shot_clip.pt"
META_PATH    = WEIGHTS_DIR / "shot_clip_meta.json"


# ─── ネットワーク定義 ─────────────────────────────────────────────────────────

def _build_model():
    """MobileNetV3-Small 特徴抽出 + LSTM 分類ヘッド。"""
    try:
        import torch
        import torch.nn as nn
        from torchvision.models import mobilenet_v3_small, MobileNet_V3_Small_Weights

        class ShotClipModel(nn.Module):
            def __init__(self):
                super().__init__()
                backbone = mobilenet_v3_small(weights=MobileNet_V3_Small_Weights.DEFAULT)
                # 分類ヘッドを除いた特徴抽出部
                self.features = nn.Sequential(*list(backbone.children())[:-1])
                self.pool = nn.AdaptiveAvgPool2d((1, 1))

                self.lstm = nn.LSTM(
                    input_size=FEAT_DIM,
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

            def extract_frame(self, frame_tensor):
                """単フレーム (1, 3, H, W) → 特徴ベクトル (1, FEAT_DIM)"""
                feat = self.features(frame_tensor)
                feat = self.pool(feat).flatten(1)
                return feat

            def forward(self, clip):
                """clip: (batch, T, 3, H, W)"""
                batch, T = clip.shape[:2]
                frames = clip.view(batch * T, *clip.shape[2:])
                feats = self.features(frames)
                feats = self.pool(feats).flatten(1)             # (batch*T, FEAT_DIM)
                feats = feats.view(batch, T, FEAT_DIM)
                out, _ = self.lstm(feats)
                return self.head(out[:, -1, :])

        return ShotClipModel()
    except ImportError:
        return None


# ─── データセット構築ユーティリティ ────────────────────────────────────────────

def extract_clip_frames(video_path: str, contact_frame: int) -> Optional[list]:
    """動画ファイルから打点前後のフレームリストを抽出する。

    Returns:
        list of numpy arrays (H, W, 3) or None
    """
    try:
        import cv2
        import numpy as np

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return None
        start = max(0, contact_frame - HALF_CLIP)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start)
        frames = []
        for _ in range(HALF_CLIP * 2 + 1):
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.resize(frame, FRAME_SIZE)
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frames.append(frame)
        cap.release()
        return frames if frames else None
    except Exception as exc:
        logger.warning("clip extract error: %s", exc)
        return None


def frames_to_tensor(frames: list, sample_n: int = SAMPLE_FRAMES):
    """フレームリストを (1, T, 3, H, W) テンソルに変換する（等間隔サンプリング）。"""
    try:
        import torch
        import numpy as np
        from torchvision.transforms.functional import normalize

        indices = np.linspace(0, len(frames) - 1, sample_n, dtype=int)
        sampled = [frames[i] for i in indices]
        arr = np.stack(sampled, axis=0).astype(np.float32) / 255.0  # (T, H, W, 3)
        arr = arr.transpose(0, 3, 1, 2)                             # (T, 3, H, W)
        t = torch.from_numpy(arr)
        mean = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
        std  = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)
        t = (t - mean) / std
        return t.unsqueeze(0)  # (1, T, 3, H, W)
    except ImportError:
        return None


# ─── 学習 ─────────────────────────────────────────────────────────────────────

def train(
    db_url: str,
    video_root: str,
    epochs: int = 30,
    batch_size: int = 8,
    lr: float = 5e-4,
    val_split: float = 0.15,
    device_str: str = "cpu",
    freeze_backbone_epochs: int = 5,
) -> dict:
    """DB + 動画ファイルから学習データを構築しクリップモデルを学習する。

    Args:
        video_root: 動画ファイルのルートディレクトリ
        freeze_backbone_epochs: 最初の N エポックは MobileNetV3 の重みを固定する
    """
    try:
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, Dataset, random_split
        import numpy as np
        from sqlalchemy import create_engine, text
    except ImportError as e:
        raise RuntimeError(f"学習に必要なパッケージがありません: {e}") from e

    from backend.analysis.shot_taxonomy import CANONICAL_SHOTS, canonicalize

    engine = create_engine(db_url)
    label_idx = {s: i for i, s in enumerate(CANONICAL_SHOTS)}

    logger.info("ShotClip: DBからストローク情報を取得中...")
    with engine.connect() as conn:
        strokes = conn.execute(text(
            """
            SELECT s.id, s.shot_type, s.timestamp_sec, m.source_fps, m.video_local_path
            FROM strokes s
            JOIN rallies r ON r.id = s.rally_id
            JOIN game_sets g ON g.id = r.set_id
            JOIN matches m ON m.id = g.match_id
            WHERE s.shot_type IS NOT NULL AND s.shot_type != ''
              AND m.video_local_path IS NOT NULL
            """
        )).fetchall()

    class ClipDataset(Dataset):
        def __init__(self, rows, label_idx, video_root, sample_n):
            self.items = []
            skipped = 0
            for row in rows:
                label = canonicalize(row.shot_type or "")
                if label not in label_idx:
                    continue
                fps = int(row.source_fps or 60)
                contact_frame = int((row.timestamp_sec or 0) * fps)
                vid = Path(video_root) / row.video_local_path
                if not vid.exists():
                    skipped += 1
                    continue
                self.items.append({
                    "video": str(vid),
                    "contact": contact_frame,
                    "label": label_idx[label],
                })
            logger.info("ClipDataset: %d サンプル（skip=%d）", len(self.items), skipped)

        def __len__(self):
            return len(self.items)

        def __getitem__(self, idx):
            import torch
            item = self.items[idx]
            frames = extract_clip_frames(item["video"], item["contact"])
            if not frames:
                # フォールバック: ゼロテンソル
                return torch.zeros(SAMPLE_FRAMES, 3, *FRAME_SIZE), item["label"]
            t = frames_to_tensor(frames, SAMPLE_FRAMES)
            if t is None:
                return torch.zeros(SAMPLE_FRAMES, 3, *FRAME_SIZE), item["label"]
            return t[0], item["label"]  # (T, 3, H, W), int

    dataset = ClipDataset(strokes, label_idx, video_root, SAMPLE_FRAMES)
    if len(dataset) < 10:
        raise RuntimeError(f"学習サンプル数が少なすぎます（{len(dataset)} 件）")

    val_size = max(1, int(len(dataset) * val_split))
    train_size = len(dataset) - val_size
    train_ds, val_ds = random_split(dataset, [train_size, val_size])

    def collate_fn(batch):
        import torch
        xs, ys = zip(*batch)
        return torch.stack(xs), torch.tensor(ys, dtype=torch.long)

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True, collate_fn=collate_fn)
    val_loader   = DataLoader(val_ds, batch_size=batch_size, collate_fn=collate_fn)

    device = torch.device(device_str)
    model = _build_model()
    if model is None:
        raise RuntimeError("torchvision が見つかりません: pip install torchvision")
    model = model.to(device)

    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    criterion = nn.CrossEntropyLoss()
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    best_val_acc = 0.0
    best_state = None

    for epoch in range(epochs):
        # バックボーン freeze 制御
        frozen = epoch < freeze_backbone_epochs
        for p in model.features.parameters():
            p.requires_grad = not frozen

        model.train()
        train_loss = 0.0
        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            optimizer.zero_grad()
            loss = criterion(model(xb), yb)
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * len(xb)
        scheduler.step()

        model.eval()
        correct = total = 0
        with torch.no_grad():
            for xb, yb in val_loader:
                xb, yb = xb.to(device), yb.to(device)
                preds = model(xb).argmax(dim=1)
                correct += (preds == yb).sum().item()
                total += len(yb)
        val_acc = correct / total if total > 0 else 0.0

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

        if (epoch + 1) % 5 == 0:
            logger.info(
                "ShotClip epoch %d/%d  train_loss=%.4f  val_acc=%.3f  backbone_frozen=%s",
                epoch + 1, epochs, train_loss / train_size, val_acc, frozen,
            )

    WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    if best_state:
        model.load_state_dict(best_state)
    torch.save(model.state_dict(), MODEL_PATH)
    meta = {
        "best_val_acc": round(best_val_acc, 4),
        "epochs": epochs,
        "half_clip": HALF_CLIP,
        "sample_frames": SAMPLE_FRAMES,
        "frame_size": list(FRAME_SIZE),
        "classes": CANONICAL_SHOTS,
        "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "samples": len(dataset),
    }
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("ShotClip: 保存完了 val_acc=%.3f → %s", best_val_acc, MODEL_PATH)
    return {"best_val_acc": best_val_acc, "epochs": epochs, "model_path": str(MODEL_PATH)}


# ─── 推論 ─────────────────────────────────────────────────────────────────────

class ShotClipClassifier:
    """学習済みクリップモデルで shot_type を推論するシングルトンラッパー。"""

    def __init__(self) -> None:
        self._model = None
        self._loaded = False
        self._device = "cpu"

    def load(self) -> bool:
        if self._loaded:
            return True
        if not MODEL_PATH.exists():
            logger.warning("ShotClip: 重みが見つかりません (%s)", MODEL_PATH)
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
            logger.info("ShotClip: ロード完了 (%s)", MODEL_PATH)
            return True
        except Exception as exc:
            logger.warning("ShotClip: ロード失敗 %s", exc)
            return False

    def predict_frames(self, frames: list) -> Optional[dict]:
        """フレームリストから shot_type を予測する。

        Args:
            frames: list of numpy arrays (H, W, 3) BGR または RGB

        Returns:
            {"shot_type": str, "confidence": float, "top3": [...]} or None
        """
        if not self.load():
            return None
        try:
            import torch

            t = frames_to_tensor(frames, SAMPLE_FRAMES)
            if t is None:
                return None
            t = t.to(self._device)

            with torch.no_grad():
                logits = self._model(t)[0]
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
            logger.warning("ShotClip predict error: %s", exc)
            return None

    def predict_video(self, video_path: str, contact_frame: int) -> Optional[dict]:
        """動画ファイルと打点フレームから直接予測する。"""
        frames = extract_clip_frames(video_path, contact_frame)
        if not frames:
            return None
        return self.predict_frames(frames)

    def get_meta(self) -> Optional[dict]:
        if not META_PATH.exists():
            return None
        try:
            return json.loads(META_PATH.read_text(encoding="utf-8"))
        except Exception:
            return None


_clip_instance: Optional[ShotClipClassifier] = None


def get_shot_clip() -> ShotClipClassifier:
    global _clip_instance
    if _clip_instance is None:
        _clip_instance = ShotClipClassifier()
    return _clip_instance
