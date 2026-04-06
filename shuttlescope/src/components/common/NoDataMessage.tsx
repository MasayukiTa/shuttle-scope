/**
 * データ不足時の案内メッセージ。
 * 「データ不足」と表示する代わりに「あとN件で表示できます」を表示する。
 */
interface NoDataMessageProps {
  sampleSize: number
  minRequired?: number
  unit?: string
}

export function NoDataMessage({ sampleSize, minRequired = 1, unit = '件' }: NoDataMessageProps) {
  const needed = Math.max(0, minRequired - sampleSize)
  return (
    <div className="py-4 text-center">
      <p className="text-sm text-gray-500">
        あと<span className="font-semibold text-gray-400 mx-0.5">{needed}</span>{unit}のデータで表示できます
      </p>
      {sampleSize > 0 && (
        <p className="text-xs text-gray-600 mt-0.5">現在 {sampleSize}{unit}</p>
      )}
    </div>
  )
}
