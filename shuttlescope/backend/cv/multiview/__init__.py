"""多視点 (2+ カメラ) 3D 解析。

姿勢崩壊 (3D 重心/体軸) や occlusion 解消のため、同じ試合を撮った複数映像を
共通のコート 3D 座標系に校正し、対応点を三角測量して 3D 復元する。

モジュール:
  court3d.py       — 既知のバドミントンコート寸法を使った単カメラ校正 (solvePnP)
  triangulate.py   — 2 射影行列 + 2D 対応点 → 3D
  temporal_sync.py — 音声に依らない映像ベース時刻同期 (motion-energy 相互相関)

設計: docs/validation の多視点メモ参照。Mavic は音声無しのため同期は映像ベースを主とする。
"""
