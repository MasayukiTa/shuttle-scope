/**
 * RallyPanel: 終了種別ボタンのアクセシブル名に得点者が含まれること (監査 #551)。
 * 同じ「アウト」「ネット」等が A 列 / B 列に並ぶため、名前だけでは誰の得点か区別できなかった。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

import { RallyPanel } from '../RallyPanel'

describe('RallyPanel end type buttons', () => {
  it('各ボタンのアクセシブル名に得点者名が入り、列は group として区別される', () => {
    render(
      <RallyPanel
        setNum={1}
        rallyNum={1}
        scoreA={0}
        scoreB={0}
        playerAName="Alice"
        playerBName="Bob"
        onConfirmRally={vi.fn()}
        onCancelRally={vi.fn()}
        isActive
      />,
    )
    const buttons = screen.getAllByRole('button').filter((b) => b.getAttribute('aria-label'))
    const labels = buttons.map((b) => b.getAttribute('aria-label') ?? '')
    expect(labels.length).toBe(12)
    expect(new Set(labels).size).toBe(12)
    expect(labels.filter((l) => l.includes('Alice')).length).toBe(6)
    expect(labels.filter((l) => l.includes('Bob')).length).toBe(6)
    expect(screen.getAllByRole('group').length).toBe(2)
  })
})
