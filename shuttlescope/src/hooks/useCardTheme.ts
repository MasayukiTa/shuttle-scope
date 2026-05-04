import { useIsLightMode } from './useIsLightMode'

/**
 * カードコンポーネント共通のテーマクラスを返すフック。
 * light / dark 両対応のクラス文字列を提供する。
 */
export function useCardTheme() {
  const isLight = useIsLightMode()
  return {
    isLight,
    // カード背景
    card: isLight ? 'bg-white border border-gray-200 shadow-sm' : 'bg-gray-800',
    // カード内部のサブセクション背景
    cardInner: isLight ? 'bg-gray-50 border border-gray-100' : 'bg-gray-700/40',
    cardInnerAlt: isLight ? 'bg-gray-100' : 'bg-gray-700/20',
    // テキスト
    textPrimary: isLight ? 'text-gray-900' : 'text-gray-200',
    textHeading: isLight ? 'text-gray-800' : 'text-gray-200',
    textSecondary: isLight ? 'text-gray-600' : 'text-gray-400',
    textMuted: isLight ? 'text-gray-500' : 'text-gray-500',
    textFaint: isLight ? 'text-gray-400' : 'text-gray-600',
    // ボーダー
    border: isLight ? 'border-gray-200' : 'border-gray-700',
    borderFaint: isLight ? 'border-gray-100' : 'border-gray-700/40',
    // テーブル
    tableHeader: isLight ? 'text-gray-500 border-b border-gray-200' : 'text-gray-500 border-b border-gray-700',
    rowBorder: isLight ? 'border-b border-gray-100' : 'border-b border-gray-700/40',
    rowHover: isLight ? 'hover:bg-gray-50' : 'hover:bg-gray-700/20',
    // その他
    loading: isLight ? 'text-gray-400' : 'text-gray-500',
    badge: isLight ? 'bg-gray-100 text-gray-700 border border-gray-300' : 'bg-gray-700 text-gray-300 border border-gray-600',
  }
}
