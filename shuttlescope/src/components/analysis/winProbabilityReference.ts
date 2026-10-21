// backend の win_probability_reference / win_probability_ci と同じ形。
// is_reference は backend が 1 か所 (reference_status) で決める。画面側で閾値を持たない。
export interface WinProbabilityReference {
  is_reference: boolean
  reason: 'sample' | 'brier' | null
  min_sample: number
  sample_size: number
}

export interface WinProbabilityInterval {
  low: number
  high: number
  n: number
}
