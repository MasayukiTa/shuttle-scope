/**
 * Pass 2 (サーブ・最終打) の保存内容を組み立てる純関数。
 *
 * 通常は「サーブ」と「最終打 (sentinel 9999)」の 2 stroke を作るが、サービスエースや
 * サービスフォルトのようにサーブ 1 打でラリーが終わる場合、最終打はサーブ自身であり
 * 別 stroke ではない。2 件作ると実在しない 2 打系列になり、rally_length・打球者交代・
 * 終端ショット分析が汚れるため、1 打ラリーは serve 1 件 + rally_length=1 にする。
 */
import type { ZoneCode } from '@/components/mobileAnnotate/AnnotateOverlay'

export interface Pass2ServeZones {
  serve_hit?: ZoneCode
  serve_land?: ZoneCode
}

// interface ではなく type: enqueue の body (Record<string, unknown>) へ渡せるようにする
export type Pass2ServeStrokeBody = {
  stroke_num: 1
  player: 'player_a' | 'player_b'
  shot_type: 'serve'
  hit_zone: ZoneCode | undefined
  land_zone: ZoneCode | undefined
}

export function serveOnlyRallyPayload(
  rally: { server: 'player_a' | 'player_b' },
  zones: Pass2ServeZones,
): { stroke: Pass2ServeStrokeBody; rallyLength: 1 } {
  return {
    stroke: {
      stroke_num: 1,
      player: rally.server,
      shot_type: 'serve',
      hit_zone: zones.serve_hit,
      land_zone: zones.serve_land,
    },
    rallyLength: 1,
  }
}
