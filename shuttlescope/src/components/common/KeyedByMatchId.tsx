import { Fragment, type ReactNode } from 'react'
import { useParams } from 'react-router-dom'

/**
 * `/…/:matchId` ルートの子を matchId ごとに作り直す (再マウント) ラッパ。
 *
 * react-router は同じ route 定義で param だけが変わる遷移 (#/annotator/1 → #/annotator/2)
 * で要素を再利用するため、useState / useRef / 「初期化済み」フラグが前の試合のまま残る。
 * その結果、新しい試合の名前に前の試合のスコア・セット・ラリー番号が表示され、
 * 入力が別の試合に保存される恐れがあった (UI 点検 A-11)。
 * key={matchId} で試合ごとに状態を分離する。
 */
export function KeyedByMatchId({ children }: { children: ReactNode }) {
  const { matchId } = useParams<{ matchId: string }>()
  return <Fragment key={matchId ?? ''}>{children}</Fragment>
}
