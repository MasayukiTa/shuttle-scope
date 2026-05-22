// ShuttleScope ESLint flat config (ESLint 10).
// 目的: 単独開発でも「複数人格 = 小規模チーム」相当の規律を強制する。
// 方針: 既存コードに大量に存在する負債は段階導入のため warn(ビルドは止めない)。
//       新規/触ったコードから直し、安定したら error に格上げしていく。
import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import reactHooks from 'eslint-plugin-react-hooks'
import i18next from 'eslint-plugin-i18next'
import globals from 'globals'

export default tseslint.config(
  // 除外
  {
    ignores: [
      'out/**', 'dist/**', 'node_modules/**',
      '**/*.config.js', '**/*.config.mjs', '**/*.config.ts',
      'scripts/**', 'electron/**',  // renderer(src) に集中。electron は別途。
      'src/styles/material-symbols-subset.css',
    ],
  },

  js.configs.recommended,
  ...tseslint.configs.recommended,

  // src/public 配下の素の JS(HTML に inject されるブラウザスクリプト)。
  // browser globals を与え、TS 由来でない undef 誤検出を抑える。
  {
    files: ['src/**/*.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'script',
      globals: { ...globals.browser },
    },
    rules: {
      'no-undef': 'off',
      '@typescript-eslint/no-unused-vars': 'off',
      'no-unused-vars': 'warn',
    },
  },

  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: { ...globals.browser, ...globals.es2022 },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: {
      'react-hooks': reactHooks,
      i18next,
    },
    rules: {
      // ── 構造ガード(god-file 物理禁止)──────────────────────────
      // 既存最大は AnnotatorPage 4796 行。まず 500 で可視化 → 段階的に下げる。
      'max-lines': ['warn', { max: 500, skipBlankLines: true, skipComments: true }],
      'max-lines-per-function': ['warn', { max: 200, skipBlankLines: true, skipComments: true }],
      complexity: ['warn', 20],

      // ── React Hooks 規約 ────────────────────────────────────────
      // 既存 18 件を wrapper 分離で解消済み → error 昇格(以後 条件付き hook を禁止)。
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',

      // ── 既存負債の段階降格(壊れ系ではないため warn)─────────────
      // TypeScript が未定義変数を型レベルで検出するため no-undef は TS では無効化(標準対応)
      'no-undef': 'off',
      'no-empty': ['warn', { allowEmptyCatch: true }],
      'no-useless-assignment': 'warn',
      'no-irregular-whitespace': 'warn',
      '@typescript-eslint/no-unused-expressions': 'warn',
      '@typescript-eslint/ban-ts-comment': 'warn',
      '@typescript-eslint/no-empty-object-type': 'warn',

      // ── i18n: JSX 直書き文字列の検出 ───────────────────────────
      // 現状大量にあるため warn。markupOnly で JSX テキストのみ対象、
      // 記号・数字のみは除外。
      // eslint-plugin-i18next v6 スキーマ: mode / jsx-attributes / words.exclude
      'i18next/no-literal-string': ['warn', {
        mode: 'jsx-text-only',  // JSX のテキストノードのみ対象 (旧 markupOnly 相当)
        'jsx-attributes': {
          exclude: ['className', 'class', 'id', 'key', 'type', 'name',
            'data-testid', 'aria-hidden', 'role', 'href', 'to', 'path', 'rel',
            'target', 'style', 'fill', 'stroke', 'viewBox', 'd', 'xmlns'],
        },
        words: {
          // 普遍的に翻訳不要なものを除外: 記号/数字のみ・解像度・ブランド名
          exclude: [
            '^\\s*[!-/:-@[-`{-~\\d\\s✓✕→←↑↓▶■・…％⚠⚡🔄📁★☆–—※•「」]+\\s*$', // 記号・絵文字・数字のみ
            '^[A-Z]$',                                      // 単一大文字ラベル (A/B 等)
            '^NET$',
            '^\\d+p$',                                      // 解像度 360p..1080p
            '^(Chrome|Edge|Firefox|Brave|Safari|Opera)$',   // ブラウザ名
            '^(H2H|EPV|RPE|CCS|PCA|MA|CV|GPU|CPU|API|URL|ID|UI|OK|NG)$', // 略語
            '^(s|ms|m|h|km|kg|MB|KB|GB|px|fps|pt|%)$',                   // 単位
          ],
        },
      }],

      // ── dead code / 型の規律 ───────────────────────────────────
      '@typescript-eslint/no-unused-vars': ['warn', {
        argsIgnorePattern: '^_', varsIgnorePattern: '^_',
      }],
      '@typescript-eslint/no-explicit-any': 'warn',
      'no-console': ['warn', { allow: ['warn', 'error'] }],
      'eqeqeq': ['warn', 'smart'],
    },
  },

  // ── admin 限定の運用画面は i18n 対象外 ──────────────────────────
  // 攻撃ログ等の技術ラベル (Method/Path/Status 等) は英語固定で読めれば十分、
  // と運用方針で合意 (2026-05-21)。i18n burndown のカウントから除外する。
  {
    files: [
      'src/pages/SecurityLogPage.tsx',
      'src/pages/AuditLogPage.tsx',
      'src/pages/AdminAnalyticsPage.tsx',
      'src/pages/AdminBillingPage.tsx',
    ],
    rules: {
      'i18next/no-literal-string': 'off',
    },
  },

  // ── テストファイルは i18n 対象外 ───────────────────────────────
  // テストはユーザに表示されない。t() 注入は useTranslation スコープが無く
  // ランタイムエラーになるため、リテラル文字列のままで正しい。
  {
    files: ['**/*.test.tsx', '**/*.test.ts', '**/__tests__/**'],
    rules: {
      'i18next/no-literal-string': 'off',
    },
  },
)
