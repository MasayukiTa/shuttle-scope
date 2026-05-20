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
      // 本来 error にすべき(条件付き hook 呼び出し等は実バグ)だが、既存 18 件の
      // 違反を一括 error 化すると lint が常時失敗するため段階導入で warn。
      // TODO: 既存 18 件を解消後 'error' へ昇格する。
      'react-hooks/rules-of-hooks': 'warn',
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
      'i18next/no-literal-string': ['warn', {
        markupOnly: true,
        ignoreAttribute: ['className', 'class', 'id', 'key', 'type', 'name',
          'data-testid', 'aria-hidden', 'role', 'href', 'to', 'path', 'rel',
          'target', 'style', 'fill', 'stroke', 'viewBox', 'd', 'xmlns'],
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
)
