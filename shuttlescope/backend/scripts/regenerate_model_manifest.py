"""モデル SHA256SUMS の生成 / 再生成 (Round 258 #8).

使い方::

    cd shuttlescope
    python -m backend.scripts.regenerate_model_manifest

実行すると `backend/models/SHA256SUMS` が再生成される。
モデルを正当に更新した直後に実行し、結果を git commit すること。
"""
from __future__ import annotations

import sys
from pathlib import Path

from backend.utils.model_integrity import (
    DEFAULT_MANIFEST_PATH,
    DEFAULT_MODELS_DIR,
    compute_manifest,
    render_manifest,
)


def main() -> int:
    print(f"scanning models in {DEFAULT_MODELS_DIR}")
    entries = compute_manifest(DEFAULT_MODELS_DIR)
    if not entries:
        print(
            f"[WARN] no model files found in {DEFAULT_MODELS_DIR}; "
            "manifest will be empty"
        )
    else:
        print(f"hashed {len(entries)} model file(s):")
        for rel, h in sorted(entries.items()):
            print(f"  {rel}  {h[:12]}...")
    text = render_manifest(entries)
    DEFAULT_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_MANIFEST_PATH.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {DEFAULT_MANIFEST_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
