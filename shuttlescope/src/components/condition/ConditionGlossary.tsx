/**
 * コンディションタブ用語解説モーダル。
 *
 * 「CCS」「F1〜F5」「Hooper Sleep」「sleep_hours」「RPE」など、
 * 数字を見ただけでは意味の取れない指標を一覧で説明する。
 *
 * Design Language v1.2 §13.5「思考を消す」: 用語を覚えなくても
 * 理解できるよう、各指標ラベルの隣に「?」アイコンを置き、
 * その場で短い説明 + 「詳細」リンクで本モーダルへ。
 */
import { _useState } from 'react'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { MIcon } from '@/components/common/MIcon'
import { N_GRAY } from '@/styles/colors'
import { useTranslation } from 'react-i18next'

interface TermDef {
  term: string
  short: string
  detail: string
  range?: string
  source?: string
}

export const CONDITION_GLOSSARY: TermDef[] = [
  {
    term: 'CCS (Composite Condition Score)',
    short: '主観コンディションを 5 因子から合成した総合スコア。0〜100、高いほど好調。',
    detail:
      '質問票 44 項目から PCA で抽出した F1〜F5 の 5 因子を統計的に合算し 0〜100 に正規化した指標。「今日の調子」を 1 つの数字で見るための要約値。CSS (Cascading Style Sheets) ではなく Composite Condition Score の略。',
    range: '0〜100',
    source: '44 項目 PCA → 重み付け加算 (backend/analysis/condition_scoring.py)',
  },
  {
    term: 'F1: 身体的疲労・回復',
    short: '筋肉痛、だるさ、息切れなど身体面の調子。',
    detail: 'PCA 第 1 因子。身体的疲労感・痛み・回復実感の主観評価を集約。低いほど疲労蓄積、高いほど回復済み。',
  },
  {
    term: 'F2: 睡眠・休養の質',
    short: '昨夜の眠り・休養の取れ具合。',
    detail: 'PCA 第 2 因子。寝つき・夜中の覚醒・起床時の爽快感・休養充足感を集約。',
  },
  {
    term: 'F3: 心理的ストレス・気分',
    short: '心理面の落ち着き・前向きさ。',
    detail: 'PCA 第 3 因子。不安・イライラ・憂鬱・気分の良さ等の主観評価を集約。低いほどストレス高。',
  },
  {
    term: 'F4: モチベーション・集中',
    short: '練習・試合への取り組み意欲と集中力。',
    detail: 'PCA 第 4 因子。やる気・集中の持続・注意散漫感を集約。',
  },
  {
    term: 'F5: 身体機能・パフォーマンス感',
    short: '今日のプレー感覚 (キレ・反応・動き出し)。',
    detail: 'PCA 第 5 因子。動きの軽さ・反応の速さ・コントロール感の主観評価を集約。',
  },
  {
    term: 'Hooper Index',
    short: '疲労・ストレス・気分・睡眠の 4 項目を合算した心理生理状態指標。',
    detail:
      'Hooper らが提唱したオーバートレーニング監視指標。4 項目をそれぞれ 1-7 段階で評価し合計 (4〜28)。高いほど状態悪化。CCS と並走させて主観コンディションを多角的に追う。',
    range: '4〜28',
    source: 'Hooper et al. (1995)',
  },
  {
    term: 'Hooper Sleep (sleep_score)',
    short: '主観的「眠れたか」を 1〜7 で評価 (Hooper Index の 1 項目)。',
    detail:
      'Hooper Index の 4 項目のうちの 1 つ。**実睡眠時間 (sleep_hours) とは別物**で、こちらは「眠りの満足度」の主観評価。長く寝ても満足度が低ければ score が低くなる。',
    range: '1 (とても良い) 〜 7 (とても悪い)',
  },
  {
    term: 'Sleep Hours (sleep_hours)',
    short: '実睡眠時間 (時間単位)。',
    detail:
      '実際に寝ていた時間。Hooper Sleep の主観評価とは独立に時系列で記録。例: 6.5h, 7.2h など。',
    range: '0〜24 時間',
  },
  {
    term: 'RPE (Rating of Perceived Exertion)',
    short: '自覚的運動強度。練習・試合の「きつさ」を 1〜10 で評価。',
    detail:
      'Borg CR10 スケール準拠の主観運動強度。1 (極めて軽い) 〜 10 (最大努力)。練習時間 (分) × RPE = セッション負荷 (Session Load) を算出。',
    range: '1〜10',
    source: 'Borg CR10',
  },
  {
    term: 'Session Load',
    short: 'セッション (練習・試合) の負荷量 = 時間 × RPE。',
    detail:
      '練習時間 (分) × RPE。週合計を出すと累積負荷量の代理指標になり、急性: 慢性 (A:C) 比でオーバートレーニング兆候の評価に使う。',
    range: '0〜数千 (単位: AU = arbitrary units)',
  },
  {
    term: 'sleep_hours / sleep_score の違い',
    short: '実時間と主観質。両方記録するのが大事。',
    detail:
      'sleep_hours = 「何時間寝たか」(時間量)、Hooper Sleep (sleep_score) = 「どれだけ眠れた感覚があったか」(質)。長時間でも質が悪いケース・短時間でも満足度高いケースがあるため、両方を独立に追跡する。',
  },
]

interface Props {
  open: boolean
  onClose: () => void
}

export function ConditionGlossary({ open, onClose }: Props) {
  const { t } = useTranslation()

  const isLight = useIsLightMode()
  if (!open) return null

  const bg = isLight ? '#ffffff' : N_GRAY[800]
  const border = isLight ? N_GRAY[200] : N_GRAY[700]
  const textTitle = isLight ? N_GRAY[900] : N_GRAY[50]
  const textBody = isLight ? N_GRAY[700] : N_GRAY[200]
  const textMuted = isLight ? N_GRAY[500] : N_GRAY[400]

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-lg"
        style={{ backgroundColor: bg, border: `1px solid ${border}` }}
        onClick={(e) => e.stopPropagation()}
      >
        <header
          className="sticky top-0 flex items-center justify-between px-5 py-3 border-b"
          style={{ backgroundColor: bg, borderColor: border }}
        >
          <h2 className="text-base font-semibold" style={{ color: textTitle }}>
            {t('auto.ConditionGlossary.title')}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="text-sm px-2 py-1 rounded"
            style={{ color: textMuted }}
          >
            <MIcon name="close" size={16} />
          </button>
        </header>
        <div className="px-5 py-4 space-y-4">
          {CONDITION_GLOSSARY.map((g) => (
            <div key={g.term} className="space-y-1">
              <div className="text-sm font-semibold" style={{ color: textTitle }}>{g.term}</div>
              <div className="text-xs" style={{ color: textBody }}>{g.short}</div>
              <div className="text-xs leading-relaxed" style={{ color: textBody }}>{g.detail}</div>
              <div className="flex flex-wrap gap-4 text-[10px]" style={{ color: textMuted }}>
                {g.range && <span>{t('auto.ConditionGlossary.range', { v: g.range })}</span>}
                {g.source && <span>{t('auto.ConditionGlossary.source', { v: g.source })}</span>}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

/**
 * ラベル横に置く「?」アイコンボタン。クリックで Glossary を開く。
 */
export function GlossaryHint({ onOpen }: { onOpen: () => void }) {
  const isLight = useIsLightMode()
  return (
    <button
      type="button"
      onClick={onOpen}
      title={t('auto.ConditionGlossary.k1')}
      className="inline-flex items-center justify-center w-4 h-4 rounded-full text-[10px]"
      style={{
        color: isLight ? N_GRAY[500] : N_GRAY[400],
        border: `1px solid ${isLight ? N_GRAY[300] : N_GRAY[600]}`,
        marginLeft: 4,
      }}
    >
      ?
    </button>
  )
}
