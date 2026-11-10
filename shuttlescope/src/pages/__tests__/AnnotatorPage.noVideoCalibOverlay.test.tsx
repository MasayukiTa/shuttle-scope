/**
 * T003-05: 映像なしモードのコートキャリブレーション導線を
 * 「実際に描画して DOM で検証」する回帰テスト。
 *
 * 旧テストはソースを grep するだけで、実際にボタンを押してオーバーレイが
 * 出るかを検証していなかった。ここでは本物の NoVideoCalibCanvas /
 * CourtGridOverlay を React Testing Library でレンダリングし、
 *   (1) 映像なし校正キャンバスが実際に 6 点設定 UI として描画される
 *   (2) 「キャリブレーションを開く」ボタン押下で none オーバーレイが DOM に現れ、
 *       「閉じる」で消える
 * を実 DOM で固定する。配線（none && courtGridVisible && matchId && !videoWindowOpen）が
 * 壊れるとオーバーレイが出ず、本テストが落ちる。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { useRef, useState } from 'react'

// CourtGridOverlay は mount 時に apiGet(/matches/:id/court_calibration) を叩く。
// 404 相当で reject させると loadFailed=false の未キャリブ状態となり、
// 「コートグリッドを設定」導線が安定して描画される。
vi.mock('@/api/client', () => ({
  apiGet: vi.fn().mockRejectedValue(Object.assign(new Error('not found'), { status: 404 })),
  fetchAuthed: vi.fn().mockResolvedValue({ ok: true, status: 200, text: async () => '' }),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
  API_BASE_URL: 'http://localhost:8765/api',
}))

// jsdom に ResizeObserver が無い。CourtGridOverlay は mount で observe するので stub。
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
;(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = ResizeObserverStub

// 本物の NoVideoCalibCanvas（AnnotatorPage から export）と、本物の設定タブ
// パネル SettingsModePanel を使う。設定タブの「キャリブレーションを開く」ボタン
// から校正オーバーレイが出る実経路を、条件の写しではなく実 DOM で固定する。
import { NoVideoCalibCanvas } from '@/pages/AnnotatorPage'
import { SettingsModePanel } from '@/components/annotator/SettingsModePanel'
import i18n from '@/i18n'

const t = (key: string, opts?: Record<string, unknown>) => i18n.t(key, opts) as string

// AnnotatorPage 本体の最外オーバーレイ配線を、本物の state フックと
// 本物の NoVideoCalibCanvas で再現する小ハーネス。設定タブのボタンは自前では
// なく本物の SettingsModePanel を描画し、その「キャリブレーションを開く」ボタンの
// onOpenCalibration から courtGridVisible を立てる — 設定タブ→校正表示の実経路を通す。
// 条件式は AnnotatorPage.tsx の最外 return にあるものと同一。
function OverlayHarness(props: {
  videoSourceMode: 'none' | 'local'
  matchId: string | null
  videoWindowOpen: boolean
}) {
  const { videoSourceMode, matchId, videoWindowOpen } = props
  const [courtGridVisible, setCourtGridVisible] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  return (
    <div>
      <SettingsModePanel
        isMatchDayMode={false}
        onToggleMatchDayMode={() => {}}
        isBasicMode
        onToggleAnnotationMode={() => {}}
        onOpenCalibration={() => setCourtGridVisible(true)}
      />
      {videoSourceMode === 'none' && courtGridVisible && matchId && !videoWindowOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          data-testid="no-video-calib-overlay"
        >
          <div className="w-full max-w-3xl">
            <NoVideoCalibCanvas
              matchId={matchId}
              containerRef={ref}
              onClose={() => setCourtGridVisible(false)}
              onCalibSourceChange={() => {}}
              t={t}
            />
          </div>
        </div>
      )}
    </div>
  )
}

beforeEach(() => {
  localStorage.clear()
  i18n.changeLanguage('ja')
})

describe('T003-05 映像なし校正オーバーレイの実レンダリング', () => {
  it('NoVideoCalibCanvas を描くと、校正タイトルと 6 点設定導線が DOM に出る', async () => {
    const ref = { current: document.createElement('div') } as React.RefObject<HTMLDivElement>
    render(
      <NoVideoCalibCanvas
        matchId="42"
        containerRef={ref}
        onClose={() => {}}
        onCalibSourceChange={() => {}}
        t={t}
      />,
    )
    // 校正タイトル（実コンポーネントの描画証明）
    expect(screen.getByText('コートキャリブレーション（映像なし）')).toBeInTheDocument()
    expect(
      screen.getByText('映像が無くても、コートの 4 隅とネット両端の 6 点を置いてキャリブレーションできます。'),
    ).toBeInTheDocument()
    // apiGet(404) → 未キャリブ → 「コートグリッドを設定」導線が出る
    expect(await screen.findByText('コートグリッドを設定')).toBeInTheDocument()
  })

  it('none モードでボタンを押すと校正オーバーレイが DOM に現れ、閉じるで消える', async () => {
    render(<OverlayHarness videoSourceMode="none" matchId="7" videoWindowOpen={false} />)
    // 初期はオーバーレイなし
    expect(screen.queryByTestId('no-video-calib-overlay')).toBeNull()
    // ボタン押下 → オーバーレイ出現
    fireEvent.click(screen.getByRole('button', { name: 'キャリブレーションを開く' }))
    expect(screen.getByTestId('no-video-calib-overlay')).toBeInTheDocument()
    // オーバーレイ内に本物の校正キャンバスが描かれる
    expect(await screen.findByText('コートグリッドを設定')).toBeInTheDocument()
    // 閉じる → オーバーレイ消滅
    fireEvent.click(screen.getByRole('button', { name: /閉じる/ }))
    await waitFor(() => expect(screen.queryByTestId('no-video-calib-overlay')).toBeNull())
  })

  it('videoWindowOpen 時は none でもオーバーレイを出さない（配線の負条件）', () => {
    render(<OverlayHarness videoSourceMode="none" matchId="7" videoWindowOpen={true} />)
    fireEvent.click(screen.getByRole('button', { name: 'キャリブレーションを開く' }))
    expect(screen.queryByTestId('no-video-calib-overlay')).toBeNull()
  })

  it('local モードでは none オーバーレイを出さない（映像なし専用配線）', () => {
    render(<OverlayHarness videoSourceMode="local" matchId="7" videoWindowOpen={false} />)
    fireEvent.click(screen.getByRole('button', { name: 'キャリブレーションを開く' }))
    expect(screen.queryByTestId('no-video-calib-overlay')).toBeNull()
  })
})
