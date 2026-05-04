# Court Calibration Tests + Benchmark Acceptance Criteria
**Date:** 2026-04-11

---

## 実装内容

### 1. コートキャリブレーション ユニットテスト

**ファイル:** `backend/tests/test_court_calibration.py`

DB やルーターに依存しない純粋な計算関数のテスト（22テスト、全パス）。

| クラス | テスト内容 |
|---|---|
| `TestComputeHomography` | 恒等変換・中点保存・台形透視変換・行列形状 |
| `TestInvertHomography` | 往復変換精度（H → H_inv → 元座標）・ネット中央Y=0.5 |
| `TestPixelToCourtZone` | 左上=A_front_left・右下=B_back_right・全18ゾーン到達・zone_id式・クランプ |
| `TestIsInsideCourt` | 正方形コート内外・台形コート・三角形・空多角形 |

**実行コマンド:**
```bash
backend/.venv/Scripts/python -m pytest backend/tests/test_court_calibration.py -v
```

---

### 2. ベンチマーク合格判定基準の追加

**ファイル:** `backend/tools/benchmark_realtime.py`

`ACCEPTANCE` 定数と `evaluate_acceptance()` 関数を追加。

| モデル | 最低（バッチ） | 理想（リアルタイム） | p95 上限 |
|---|---|---|---|
| TrackNet | 1.0 fps | 10.0 fps | 2000 ms |
| YOLO (1/6間引き) | 3.0 fps | 10.0 fps | 500 ms |

- `print_report()` の末尾に合格判定セクションを追加
- `__main__` が合格なら exit 0、不合格なら exit 1 で終了
- CI での回帰検知に使用可能

---

## 残り（人間検証が必要なもの）

- 実映像で上記テストが示す「ゾーン正確性」が実際の着地ゾーンと一致するか確認（P2）
- 実機でベンチマークを実行し、合格基準が妥当かを確認（P4）
