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
      { titleKey: 'tutorials.analysis_reading.tabs.title',
        bodyKey:  'tutorials.analysis_reading.tabs.body',
        target:   '[data-tutorial="dashboard.topNav"]' },
      { titleKey: 'tutorials.analysis_reading.confidence.title',
        bodyKey:  'tutorials.analysis_reading.confidence.body' },
      { titleKey: 'tutorials.analysis_reading.epv.title',
        bodyKey:  'tutorials.analysis_reading.epv.body' },
      { titleKey: 'tutorials.analysis_reading.growth.title',
        bodyKey:  'tutorials.analysis_reading.growth.body' },
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
