import { AlertTriangle } from 'lucide-react'

interface SampleWarningProps {
  sampleSize: number
  threshold?: number
  message?: string
}

/**
 * サンプル数警告コンポーネント
 * サンプルが少ない場合に警告を表示
 */
export function SampleWarning({ sampleSize, threshold = 500, message }: SampleWarningProps) {
  if (sampleSize >= threshold) return null

  return (
    <div className="flex items-start gap-2 p-3 rounded bg-yellow-900/20 border border-yellow-600/50 text-yellow-300 text-sm">
      <AlertTriangle size={16} className="mt-0.5 shrink-0" />
      <p>{message ?? `サンプル数が少ないため（${sampleSize}球）、解析結果の信頼度が低い状態です。データを蓄積してから再解析することを推奨します。`}</p>
    </div>
  )
}
