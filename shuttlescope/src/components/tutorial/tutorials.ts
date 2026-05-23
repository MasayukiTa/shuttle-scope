/**
 * 全ユーザ共通のチュートリアル定義。
 *
 * 表示ポリシー: role に関係なく同じステップを表示する (運用シンプル優先)。
 *
 * 新形式: 各 step は titleKey / bodyKey を持ち、TutorialOverlay 側で
 * `t(titleKey)` / `t(bodyKey)` を呼んで i18n から本文を取得する。
 * 旧形式 (title/body 直書き) も後方互換のために残している。
 *
 * 新規 tutorial / step を追加する場合は:
 *   1. このファイルに titleKey/bodyKey/target を書く
 *   2. ja.json と en.json の `tutorials.<id>.<stepKey>.{title,body}` に文言を追加
 *   3. tutorial 自体のタイトルは `tutorials.<id>._title`
 */
import type { TutorialDef } from './TutorialOverlay'

export const TUTORIALS: Record<string, TutorialDef> = {
  mobile_annotate_pass: {
    id: 'mobile_annotate_pass',
    titleKey: 'tutorials.mobile_annotate_pass._title',
    steps: [
      { titleKey: 'tutorials.mobile_annotate_pass.intro.title',
        bodyKey:  'tutorials.mobile_annotate_pass.intro.body' },
      { titleKey: 'tutorials.mobile_annotate_pass.passSwitch.title',
        bodyKey:  'tutorials.mobile_annotate_pass.passSwitch.body',
        target:   '[data-tutorial="mobileAnnotate.passSwitch"]' },
      { titleKey: 'tutorials.mobile_annotate_pass.pass1.title',
        bodyKey:  'tutorials.mobile_annotate_pass.pass1.body' },
      { titleKey: 'tutorials.mobile_annotate_pass.pass2.title',
        bodyKey:  'tutorials.mobile_annotate_pass.pass2.body' },
      { titleKey: 'tutorials.mobile_annotate_pass.pass3.title',
        bodyKey:  'tutorials.mobile_annotate_pass.pass3.body' },
      { titleKey: 'tutorials.mobile_annotate_pass.offline.title',
        bodyKey:  'tutorials.mobile_annotate_pass.offline.body' },
    ],
  },
  mobile_court_calibration: {
    id: 'mobile_court_calibration',
    titleKey: 'tutorials.mobile_court_calibration._title',
    steps: [
      { titleKey: 'tutorials.mobile_court_calibration.what.title',
        bodyKey:  'tutorials.mobile_court_calibration.what.body' },
      { titleKey: 'tutorials.mobile_court_calibration.loupe.title',
        bodyKey:  'tutorials.mobile_court_calibration.loupe.body' },
      { titleKey: 'tutorials.mobile_court_calibration.retry.title',
        bodyKey:  'tutorials.mobile_court_calibration.retry.body' },
    ],
  },
  desktop_annotator: {
    id: 'desktop_annotator',
    titleKey: 'tutorials.desktop_annotator._title',
    steps: [
      { titleKey: 'tutorials.desktop_annotator.welcome.title',
        bodyKey:  'tutorials.desktop_annotator.welcome.body' },
      { titleKey: 'tutorials.desktop_annotator.modeTabs.title',
        bodyKey:  'tutorials.desktop_annotator.modeTabs.body',
        target:   '[data-tutorial="annotator.modeTabs"]' },
      { titleKey: 'tutorials.desktop_annotator.videoPane.title',
        bodyKey:  'tutorials.desktop_annotator.videoPane.body',
        target:   '[data-tutorial="annotator.videoPane"]' },
      { titleKey: 'tutorials.desktop_annotator.rallyPanel.title',
        bodyKey:  'tutorials.desktop_annotator.rallyPanel.body',
        target:   '[data-tutorial="annotator.rallyPanel"]' },
      { titleKey: 'tutorials.desktop_annotator.hitZone.title',
        bodyKey:  'tutorials.desktop_annotator.hitZone.body',
        target:   '[data-tutorial="annotator.hitZone"]' },
      { titleKey: 'tutorials.desktop_annotator.shotTypes.title',
        bodyKey:  'tutorials.desktop_annotator.shotTypes.body',
        target:   '[data-tutorial="annotator.shotTypes"]' },
      { titleKey: 'tutorials.desktop_annotator.historyStrip.title',
        bodyKey:  'tutorials.desktop_annotator.historyStrip.body',
        target:   '[data-tutorial="annotator.historyStrip"]' },
      { titleKey: 'tutorials.desktop_annotator.commandPalette.title',
        bodyKey:  'tutorials.desktop_annotator.commandPalette.body' },
      { titleKey: 'tutorials.desktop_annotator.flow.title',
        bodyKey:  'tutorials.desktop_annotator.flow.body' },
    ],
  },
  analysis_reading: {
    id: 'analysis_reading',
    titleKey: 'tutorials.analysis_reading._title',
    steps: [
      // 1. Welcome (center modal, no target) — demo データであることを伝える
      { titleKey: 'tutorials.analysis_reading.welcome.title',
        bodyKey:  'tutorials.analysis_reading.welcome.body' },
      // 2. Top tabs
      { titleKey: 'tutorials.analysis_reading.tabs.title',
        bodyKey:  'tutorials.analysis_reading.tabs.body',
        target:   '[data-tutorial="dashboard.topNav"]' },
      // 3. Match / period picker
      { titleKey: 'tutorials.analysis_reading.matchPicker.title',
        bodyKey:  'tutorials.analysis_reading.matchPicker.body',
        target:   '[data-tutorial="dashboard.matchPicker"]' },
      // 4. Confidence badge (overview)
      { titleKey: 'tutorials.analysis_reading.confidenceBadge.title',
        bodyKey:  'tutorials.analysis_reading.confidenceBadge.body',
        target:   '[data-tutorial="dashboard.confidenceBadge"]' },
      // 5. Quick summary card (overview)
      { titleKey: 'tutorials.analysis_reading.quickSummary.title',
        bodyKey:  'tutorials.analysis_reading.quickSummary.body',
        target:   '[data-tutorial="dashboard.quickSummary"]' },
      // 6. Court heatmap (overview)
      { titleKey: 'tutorials.analysis_reading.epvHeatmap.title',
        bodyKey:  'tutorials.analysis_reading.epvHeatmap.body',
        target:   '[data-tutorial="dashboard.epvHeatmap"]' },
      // 7. Shot win/loss (advanced — may not be visible if not on that tab)
      { titleKey: 'tutorials.analysis_reading.shotWinLoss.title',
        bodyKey:  'tutorials.analysis_reading.shotWinLoss.body',
        target:   '[data-tutorial="dashboard.shotWinLoss"]' },
      // 8. Growth timeline (growth tab)
      { titleKey: 'tutorials.analysis_reading.growthTimeline.title',
        bodyKey:  'tutorials.analysis_reading.growthTimeline.body',
        target:   '[data-tutorial="dashboard.growthTimeline"]' },
      // 9. Research notice (research tab)
      { titleKey: 'tutorials.analysis_reading.researchNotice.title',
        bodyKey:  'tutorials.analysis_reading.researchNotice.body',
        target:   '[data-tutorial="dashboard.researchNotice"]' },
      // 10. Confidence (existing — center modal)
      { titleKey: 'tutorials.analysis_reading.confidence.title',
        bodyKey:  'tutorials.analysis_reading.confidence.body' },
      // 11. EPV (existing)
      { titleKey: 'tutorials.analysis_reading.epv.title',
        bodyKey:  'tutorials.analysis_reading.epv.body' },
      // 12. Growth framing (existing)
      { titleKey: 'tutorials.analysis_reading.growth.title',
        bodyKey:  'tutorials.analysis_reading.growth.body' },
      // 13. Closing
      { titleKey: 'tutorials.analysis_reading.closing.title',
        bodyKey:  'tutorials.analysis_reading.closing.body' },
    ],
  },
  body_disclosure_toggle: {
    id: 'body_disclosure_toggle',
    titleKey: 'tutorials.body_disclosure_toggle._title',
    steps: [
      { titleKey: 'tutorials.body_disclosure_toggle.where.title',
        bodyKey:  'tutorials.body_disclosure_toggle.where.body',
        target:   '[data-tutorial="condition.disclosureToggle"]' },
      { titleKey: 'tutorials.body_disclosure_toggle.revoke.title',
        bodyKey:  'tutorials.body_disclosure_toggle.revoke.body' },
      { titleKey: 'tutorials.body_disclosure_toggle.impact.title',
        bodyKey:  'tutorials.body_disclosure_toggle.impact.body' },
    ],
  },
}

export type TutorialId = keyof typeof TUTORIALS
