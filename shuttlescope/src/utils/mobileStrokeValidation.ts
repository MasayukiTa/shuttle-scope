/**
 * モバイル注釈 (Pass 3) の送信前クライアント検証。
 *
 * backend/utils/validators.py の validate_stroke と同じ整合性ルール。UI が出した値が
 * 必ず validate_stroke を通る形で送られるようにし、422 → mobileAnnotateQueue の
 * manualRetry 化による「無言ドロップ (アノテ消失)」を防ぐ。
 *
 * smash × NL/NC/NR は競技上成立する (急角度でネット寄りの前方へ落ちる) ため、
 * backend 同様ここでも拒否しない。backend 側は警告 (UNUSUAL_COMBINATIONS) として扱う。
 */
import type { ZoneCode } from '@/components/mobileAnnotate/AnnotateOverlay'

export const SERVICE_TYPES: readonly string[] = ['short_service', 'long_service']

// 各 shot_type が物理的に着地できないゾーン (backend INVALID_COMBINATIONS と一致)。
export const INVALID_LAND_ZONES: Record<string, readonly ZoneCode[]> = {
  short_service: ['BL', 'BC', 'BR'],  // ショートサーブはバックへ届かない
  net_shot: ['BL', 'BC', 'BR'],       // ネットショットはバックへ届かない
}

export type StrokeValidationError = 'cant_reach_land' | 'invalid_land' | 'service_not_first'

/** 送信前のクライアント検証。null なら OK。cant_reach は着地点を持てない。 */
export function strokeValidationError(
  shot: string,
  land: ZoneCode | null,
  strokeNum: number,
): StrokeValidationError | null {
  if (shot === 'cant_reach') return land != null ? 'cant_reach_land' : null
  if (land != null && INVALID_LAND_ZONES[shot]?.includes(land)) return 'invalid_land'
  if (SERVICE_TYPES.includes(shot) && strokeNum !== 1) return 'service_not_first'
  return null
}

/** Pass2 が作るラリー先頭のサーブ ('serve') と、サーブ種別 (short/long_service)。 */
const SERVE_SHOTS: readonly string[] = ['serve', ...SERVICE_TYPES]

/**
 * 1球目のサーブを Pass3 で非サーブ (smash 等) へ変えようとしているか (監査 #795)。
 * 防ぐ事象: 正規 UI 操作だけでラリー先頭のサーブ情報を失い、サーブ勝率・3球目パターン・
 * 遷移行列が「サーブの無いラリー」を数える。現在の球が 1 球目のサーブ系のときだけ
 * 非サーブへの変更を拒否する (途中から記録した 1 球目の非サーブは対象外)。
 */
export function isServeDowngrade(
  strokeNum: number,
  currentShot: string | null | undefined,
  nextShot: string,
): boolean {
  if (strokeNum !== 1 || !currentShot || !SERVE_SHOTS.includes(currentShot)) return false
  return !SERVICE_TYPES.includes(nextShot)
}

const ZONE_CODES: readonly string[] = ['BL', 'BC', 'BR', 'ML', 'MC', 'MR', 'NL', 'NC', 'NR']

/** 保存済みの文字列が 9 分割ゾーンのコードか (コート外・ネット接触は false)。 */
export function asZoneCode(v: string | null | undefined): ZoneCode | null {
  return v != null && ZONE_CODES.includes(v) ? (v as ZoneCode) : null
}
