// Recharts の Tooltip / クリックイベントは型推論が緩く any を要求してくる。
// プロジェクト内で共有するための最低限の interface を定義する。

export interface RechartsTooltipPayloadItem {
  dataKey?: string | number
  name?: string | number
  value?: number | string
  color?: string
  payload?: Record<string, unknown>
}

export interface RechartsTooltipProps {
  active?: boolean
  payload?: RechartsTooltipPayloadItem[]
  label?: string | number
}

export interface RechartsClickPayload {
  activePayload?: Array<{ payload?: Record<string, unknown> }>
  activeLabel?: string | number
  activeTooltipIndex?: number
}
