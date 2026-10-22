/**
 * コンディションタブ用語解説モーダル。
 *
 * 「CCS」「F1〜F5」「Hooper Sleep」「睡眠時間」「RPE」など、
 * 数字を見ただけでは意味の取れない指標を一覧で説明する。
 *
 * Design Language v1.2 §13.5「思考を消す」: 用語を覚えなくても
 * 理解できるよう、各指標ラベルの隣に「?」アイコンを置き、
 * その場で短い説明 + 「詳細」リンクで本モーダルへ。
 */
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
      '質問票の回答から、身体の疲れ・睡眠・気分・意欲・プレーの感覚の 5 つの面を合成し、0〜100 にした総合スコアです。「今日の調子」を 1 つの数字で見るための要約値です。',
    range: '0〜100',
  },
  {
    term: 'F1: 身体的疲労・回復',
    short: '筋肉痛、だるさ、息切れなど身体面の調子。',
    detail: '疲れ・痛み・回復した実感を自己評価でまとめた値です。低いほど疲れがたまり、高いほど回復しています。',
  },
  {
    term: 'F2: 睡眠・休養の質',
    short: '昨夜の眠り・休養の取れ具合。',
    detail: '寝つき・夜中に目が覚めたか・起きたときの爽快感・休めた実感をまとめた値です。',
  },
  {
    term: 'F3: 心理的ストレス・気分',
    short: '心理面の落ち着き・前向きさ。',
    detail: '不安・イライラ・気分の落ち込み・気分の良さをまとめた値です。低いほどストレスが高い状態です。',
  },
  {
    term: 'F4: モチベーション・集中',
    short: '練習・試合への取り組み意欲と集中力。',
    detail: 'やる気・集中の続きやすさ・気の散りやすさをまとめた値です。',
  },
  {
    term: 'F5: 身体機能・パフォーマンス感',
    short: '今日のプレー感覚 (キレ・反応・動き出し)。',
    detail: '動きの軽さ・反応の速さ・思いどおりに動かせる感覚をまとめた値です。',
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
    term: 'Hooper Sleep (睡眠の主観評価)',
    short: '主観的「眠れたか」を 1〜7 で評価 (Hooper Index の 1 項目)。',
    detail:
      'Hooper Index の 4 項目のうちの 1 つです。実際の睡眠時間とは別のもので、「どれだけ眠れた感じがしたか」を答えます。長く寝ても満足度が低ければ、点数は悪くなります。',
    range: '1 (とても良い) 〜 7 (とても悪い)',
  },
  {
    term: '睡眠時間',
    short: '実睡眠時間 (時間単位)。',
    detail:
      '実際に寝ていた時間です。Hooper Sleep の主観評価とは別に、日ごとに記録します。例: 6.5 時間、7.2 時間。',
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
    range: '0〜数千 (単位: AU、任意単位)',
  },
  {
    term: '睡眠時間と睡眠の質の違い',
    short: '実時間と主観質。両方記録するのが大事。',
    detail:
      '睡眠時間は「何時間寝たか」、Hooper Sleep は「どれだけ眠れた感じがしたか」を表します。長く寝ても満足できない日や、短くても満足できる日があるため、両方を別々に見ます。',
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

  const bg = 'var(--ss-surface-1)'
  const border = 'var(--ss-border)'
  const textTitle = 'var(--ss-t1)'
  const textBody = 'var(--ss-t2)'
  const textMuted = 'var(--ss-t3)'

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-ss-lg"
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
          <button aria-label={t('app.close')}
            type="button"
            onClick={onClose}
            className="text-sm px-2 py-1 rounded-ss-sm"
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
  // 2026-05-26: module-scope export helper。親の useTranslation の t は
  // 見えないので自前で取得する。
  const { t } = useTranslation()
  const isLight = useIsLightMode()
  return (
    <button
      type="button"
      onClick={onOpen}
      title={t('auto.ConditionGlossary.k1')}
      className="inline-flex items-center justify-center w-4 h-4 rounded-full text-[10px]"
      style={{
        color: 'var(--ss-t3)',
        border: '1px solid var(--ss-border-strong)',
        marginLeft: 4,
      }}
    >
      ?
    </button>
  )
}
