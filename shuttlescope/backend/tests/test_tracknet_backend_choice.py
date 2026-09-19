"""video_import が TrackNet のバックエンドを固定していた件。

`video_import.py` は `get_inference("openvino")` を
「GPU優先バックエンドを明示」というコメント付きで固定していた。
**OpenVINO の "GPU" は Intel の GPU を指す。** 本番機は RTX 5060 Ti を
積んでおり、この指定では NVIDIA のカードを遊ばせたまま Intel iGPU で
推論していた。

実測 (2026-09-20、本番機 MiniTakeuchi、実試合映像 1920x1080 29.97fps、
同じ 60 triple を同じ順で):

    openvino : 1557.9 ms / 推論   (0.6 推論/s)
    cuda     :   16.0 ms / 推論  (62.4 推論/s)   = 97 倍

`inference.py` の docstring は "auto" の優先順を
「ONNX CUDA → DirectML → OpenVINO → ONNX CPU → TensorFlow」と書いており、
1 番目の説明にこのカードを名指ししている。固定する理由が無かった。

CUDA の無い K10 ワーカーでは "auto" が OpenVINO へ落ちるので、
分散実行も壊れない。
"""
from __future__ import annotations

import pathlib
import re


SRC = (pathlib.Path(__file__).resolve().parents[1]
       / "routers" / "video_import.py").read_text(encoding="utf-8")


class TestTheBackendIsNotPinnedToOpenvino:
    def test_get_inference_is_called_with_auto(self):
        calls = re.findall(r'get_inference\(\s*"([a-z_]+)"', SRC)
        assert calls, "get_inference の呼び出しが見つからない"
        assert all(c == "auto" for c in calls), (
            "video_import が TrackNet バックエンドを固定している: %r" % (calls,)
        )

    def test_openvino_is_not_pinned(self):
        assert 'get_inference("openvino")' not in SRC


class TestTheSamplingDefaultReachesAutoFilled:
    """既定のサンプリング率が auto_filled の閾値に届くこと。

    10fps では Wilson 下限 0.68 で suggested 止まり。届かないと
    「CV は走ったが全部要確認」になり、補助として機能しない。
    """

    def test_default_is_at_least_15(self):
        m = re.search(r'CV_TRACKNET_SAMPLE_FPS",\s*"(\d+(?:\.\d+)?)"', SRC)
        assert m, "既定値の指定が見つからない"
        assert float(m.group(1)) >= 15.0, (
            "既定サンプリングが %s fps で auto_filled に届かない" % m.group(1)
        )

    def test_the_measurement_is_recorded_next_to_the_default(self):
        """数字の根拠をコードの隣に残しておくこと。

        「GPU 時間と相談して」とだけ書いてあったせいで、
        実際には Intel iGPU の速度と相談していたことに誰も気づかなかった。
        """
        assert "1557.9" in SRC and "16.0" in SRC, "実測値がコメントに残っていない"
