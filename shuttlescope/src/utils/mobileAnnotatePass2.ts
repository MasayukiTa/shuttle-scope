/**
 * Pass 2 (サーブ・最終打) の保存内容を組み立てる純関数。
 *
 * 通常は「サーブ」と「最終打 (sentinel 9999)」の 2 stroke を作るが、サービスエースや
 * サービスフォルトのようにサーブ 1 打でラリーが終わる場合、最終打はサーブ自身であり
 * 別 stroke ではない。2 件作ると実在しない 2 打系列になり、rally_length・打球者交代・
 * 終端ショット分析が汚れるため、1 打ラリーは serve 1 件 + rally_length=1 にする。
 */
import type { ZoneCode } from '@/components/mobileAnnotate/AnnotateOverlay'
import type { HitterSlot } from '@/utils/mobileAnnotateDoubles'

export interface Pass2ServeZones {
  serve_hit?: ZoneCode
  serve_land?: ZoneCode
}

// interface ではなく type: enqueue の body (Record<string, unknown>) へ渡せるようにする
export type Pass2ServeStrokeBody = {
  stroke_num: 1
  player: HitterSlot
  shot_type: 'serve'
  hit_zone: ZoneCode | undefined
  land_zone: ZoneCode | undefined
  // 人が画面で指定した入力であることを残す (未指定だと分析側で全て unknown になる)
  source_method: 'manual'
  hit_zone_source?: 'manual'
}

/**
 * @param serverSlot ダブルスで選ばれたサーバの個人 slot。省略時はチーム値 (rally.server)。
 */
export function serveOnlyRallyPayload(
  rally: { server: 'player_a' | 'player_b' },
  zones: Pass2ServeZones,
  serverSlot?: HitterSlot,
): { stroke: Pass2ServeStrokeBody; rallyLength: 1 } {
  return {
    stroke: {
      stroke_num: 1,
      player: serverSlot ?? rally.server,
      shot_type: 'serve',
      hit_zone: zones.serve_hit,
      land_zone: zones.serve_land,
      source_method: 'manual',
      ...(zones.serve_hit ? { hit_zone_source: 'manual' as const } : {}),
    },
    rallyLength: 1,
  }
}
