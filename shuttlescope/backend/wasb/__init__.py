"""WASB-SBDT shuttle detection (HRNet backbone).

Alternative to the current TrackNet-family detector (backend/tracknet; not TrackNet V3, see its header) for shuttle tracking, optimized for diverse
camera angles and frame rates. See docs/research/2026-05-24_wasb_vs_tracknet_player_a.md
for benchmark vs that detector (0% -> 30.9% detection on 1080p 60fps doubles).
"""
