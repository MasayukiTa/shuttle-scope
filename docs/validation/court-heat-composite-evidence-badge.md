# Validation: CourtHeatModal 合成タブ改善 & EvidenceBadge 視認性向上

## 変更日: 2026-04-14

## 変更ファイル

- `shuttlescope/src/components/analysis/CourtHeatModal.tsx`
- `shuttlescope/src/components/dashboard/EvidenceBadge.tsx`

---

## CourtHeatModal — 合成タブのタイルクリック対応

### 変更内容

1. **`interactive` を常に `true` に変更**  
   合成モードでもコートのタイルがクリック可能になった。

2. **`onZoneSelect` の合成モードガードを削除**  
   `mode !== 'composite'` の条件を除去し、全モードで `setSelectedZone` が呼び出されるようになった。

3. **着地点ゾーン詳細クエリを追加**  
   合成モード専用で `type: 'land'` のクエリを新設。打点（`type: 'hit'`）と着地点の両方を取得。

4. **右パネルを合成モード対応**  
   合成モードで zone を選択した場合、打点・着地点の詳細を左右 2 カラムで表示。ラベルに色分け（青=打点 / オレンジ=着地点）。

5. **合成モード注意書きテキストの変更**  
   旧: 「着地点データは点対称変換（ネット中心）で自コート座標系に変換済みです。可視化補助専用です。」  
   新: 「着地点はネット中心で点対称変換し、自コート座標に重ね合わせています。タイルをクリックして打点・着地点の詳細を確認できます。」

6. **「ゾーンをクリックすると詳細を表示」ヒントを合成モードにも表示**

### 確認事項

- [ ] 合成タブでタイルをクリックすると打点・着地点の詳細が両方表示される
- [ ] 打点タブ・着地点タブでは従来通り単一の詳細パネルが表示される
- [ ] 別のタイルをクリックすると両方のクエリが更新される
- [ ] タイルを再クリックすると選択が解除される
- [ ] モード切替時に selectedZone がリセットされる（既存動作）

---

## EvidenceBadge — ダークモード視認性向上

### 変更内容

| 項目 | 旧 | 新 |
|------|----|----|
| stable ダーク | `bg-emerald-900/50 border-emerald-600 text-emerald-300` | `bg-emerald-900/70 border-emerald-500 text-emerald-200` |
| advanced ダーク | `bg-blue-900/50 border-blue-600 text-blue-300` | `bg-blue-900/70 border-blue-500 text-blue-200` |
| research ダーク | `bg-amber-900/50 border-amber-600 text-amber-300` | `bg-amber-900/70 border-amber-500 text-amber-200` |
| metaText ダーク | `text-gray-500 border border-gray-700` | `text-gray-300 border border-gray-600` |
| sampleText ダーク | `text-gray-600` | `text-gray-400` |

ライトモードのスタイルは変更なし。

### 確認事項

- [ ] ダークモードでティアバッジ（安定/詳細/研究）の文字と背景が明確に視認できる
- [ ] エビデンスレベルラベル（探索的など）が読める
- [ ] N= サンプルサイズ表示が視認できる
- [ ] ライトモードで外観が崩れていない

---

## ビルド確認

```
npm run build → ✓ built in 5.25s (エラーなし)
```
