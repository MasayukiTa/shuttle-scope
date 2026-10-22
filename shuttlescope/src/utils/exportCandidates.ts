// エクスポートの候補にしてよい試合かを分類する。
//
// 試合テーブルに「検証用」「デモ」を示すフラグは無い (backend/db/models.py の Match を確認済み)。
// そのため、監査で実際に一覧へ混ざっていた次の 3 種類を、ここ 1 か所で見分ける。
//   - 日付が不正   例: 0001-01-01。API の year 検索の下限 (1900) より前は不正とみなす
//   - 未完了       result が unfinished
//   - 検証用       大会名が BIAS_SEED / DEMO / TEST (または デモ / テスト) で始まる
// 既定では valid 以外を候補から外し、「すべて選択」でも持ち出さない。

export type ExportMatchKind = 'valid' | 'invalid_date' | 'unfinished' | 'internal'

export interface ExportCandidate {
  date?: string | null
  tournament?: string | null
  result?: string | null
}

// API の year クエリが受け付ける下限 (backend/routers/matches.py list_matches: ge=1900) に合わせる
const MIN_VALID_YEAR = 1900

const INTERNAL_TOURNAMENT = /^\s*(?:BIAS_SEED|DEMO|TEST|デモ|テスト)(?:[\s_\-:：]|$)/i

export function classifyExportMatch(m: ExportCandidate): ExportMatchKind {
  const year = Number.parseInt(String(m.date ?? '').slice(0, 4), 10)
  if (!Number.isFinite(year) || year < MIN_VALID_YEAR) return 'invalid_date'
  if (INTERNAL_TOURNAMENT.test(m.tournament ?? '')) return 'internal'
  if (m.result === 'unfinished') return 'unfinished'
  return 'valid'
}
