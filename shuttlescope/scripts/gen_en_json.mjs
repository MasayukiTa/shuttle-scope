#!/usr/bin/env node
/**
 * Generate en.json skeleton from ja.json.
 * - Core sections (app, nav, auth, roles, end_types, shot_categories, video, theme,
 *   common buttons, etc.) are translated manually in TRANSLATIONS below.
 * - All other keys are omitted from en.json; i18next fallbackLng='ja' will
 *   surface Japanese until they are translated.
 */
import fs from 'node:fs'
import path from 'node:path'

const ROOT = process.cwd()
const ja = JSON.parse(fs.readFileSync(path.join(ROOT, 'src/i18n/ja.json'), 'utf8'))

// ── manual translations for frequently visible keys ────────────────────────
const EN = {
  app: {
    title: 'ShuttleScope',
    close: 'Close',
    loading: 'Loading...',
    saving: 'Saving...',
    saved: 'Saved',
    save: 'Save',
    cancel: 'Cancel',
    confirm: 'OK',
    delete: 'Delete',
    edit: 'Edit',
    add: 'Add',
    back: 'Back',
    next: 'Next',
    yes: 'Yes',
    no: 'No',
    settings: 'Settings',
    language: 'Language',
  },
  nav: {
    annotator: 'Annotator',
    matches: 'Matches',
    players: 'Players',
    dashboard: 'Dashboard',
    analysis: 'Analysis',
    settings: 'Settings',
    sharing: 'Sharing',
    condition: 'Condition',
    reports: 'Reports',
    prediction: 'Prediction',
    cluster: 'Cluster',
    notifications: 'Notifications',
    benchmark: 'Benchmark',
    annotation: 'Annotation',
  },
  roles: {
    analyst: 'Analyst',
    coach: 'Coach',
    player: 'Player',
    admin: 'Admin',
  },
  auth: {
    login: 'Log in',
    logout: 'Log out',
    username: 'Username',
    password: 'Password',
    login_button: 'Log in',
    role: {
      analyst: 'Analyst',
      coach: 'Coach',
      player: 'Player',
      admin: 'Admin',
    },
  },
  end_types: {
    ace: 'Ace',
    forced_error: 'Forced error',
    unforced_error: 'Unforced error',
    net: 'Net',
    out: 'Out',
    cant_reach: "Can't reach",
  },
  shot_categories: {
    clear: 'Clear',
    smash: 'Smash',
    drop: 'Drop',
    drive: 'Drive',
    net: 'Net',
    push: 'Push',
    service: 'Service',
    lift: 'Lift',
    other: 'Other',
  },
  video: {
    play: 'Play',
    pause: 'Pause',
    frame_back: 'Prev frame',
    frame_forward: 'Next frame',
    seek_back: '-10s',
    seek_forward: '+10s',
    speed: 'Speed',
    youtube_warning: 'Frame stepping is not available for YouTube videos',
  },
  theme: {
    dark: 'Dark',
    light: 'Light',
  },
  confidence: {
    high: 'High',
    medium: 'Medium',
    low: 'Low',
    insufficient: 'Insufficient data',
  },
  settings: {
    ui: {
      theme: 'Theme',
      theme_hint: 'Switches the overall app color scheme.',
      dark: 'Dark',
      light: 'Light',
      language: 'Language',
      language_hint: 'Switches the UI language. Untranslated text stays in Japanese.',
      language_ja: '日本語',
      language_en: 'English',
      restart_app: 'Restart app',
      restart_app_btn: 'Restart',
    },
  },
  error_boundary: {
    title: '\u26A0 A display error occurred',
    error_message_label: 'Error message',
    no_detail: '(no detail)',
    stack_trace_label: 'Stack trace',
    copy_button: 'Copy error',
    copied: 'Copied \u2713',
    reload_button: 'Reload page',
    footer_hint: 'Please use "Copy error" to send the report to the developer.',
  },
  no_data_message: {
    unit_default: 'items',
    prefix: 'Need',
    suffix: 'more to display',
    current: 'Currently',
  },
}

fs.writeFileSync(
  path.join(ROOT, 'src/i18n/en.json'),
  JSON.stringify(EN, null, 2) + '\n',
  'utf8'
)

// Rough coverage stats
function countKeys(obj) {
  let n = 0
  for (const v of Object.values(obj)) {
    if (v && typeof v === 'object') n += countKeys(v)
    else n++
  }
  return n
}
console.log(`ja.json keys: ${countKeys(ja)}`)
console.log(`en.json keys: ${countKeys(EN)} (the rest fall back to ja)`)
