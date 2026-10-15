import { describe, expect, it } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom'
import { useRef, useState } from 'react'

import { KeyedByMatchId } from '../KeyedByMatchId'
import { useAnnotationStore, isStoreForMatch } from '@/store/annotationStore'

/** AnnotatorPage と同じく「初回だけ初期化」する useRef ガードと useState を持つ疑似ページ */
function FakePage() {
  const [score, setScore] = useState(0)
  const initStarted = useRef(false)
  if (!initStarted.current) initStarted.current = true
  return (
    <div>
      <span data-testid="score">{score}</span>
      <button onClick={() => setScore((s) => s + 1)}>point</button>
      <span data-testid="init">{String(initStarted.current)}</span>
    </div>
  )
}

function Nav() {
  const navigate = useNavigate()
  return <button onClick={() => navigate('/annotator/2')}>go2</button>
}

describe('KeyedByMatchId (A-11)', () => {
  it('試合 ID が変わると子の state が持ち越されない', () => {
    render(
      <MemoryRouter initialEntries={['/annotator/1']}>
        <Nav />
        <Routes>
          <Route
            path="/annotator/:matchId"
            element={<KeyedByMatchId><FakePage /></KeyedByMatchId>}
          />
        </Routes>
      </MemoryRouter>,
    )
    fireEvent.click(screen.getByText('point'))
    fireEvent.click(screen.getByText('point'))
    expect(screen.getByTestId('score').textContent).toBe('2')
    fireEvent.click(screen.getByText('go2'))
    expect(screen.getByTestId('score').textContent).toBe('0')
  })
})

describe('annotationStore.clearMatch / isStoreForMatch (A-11)', () => {
  it('clearMatch は前の試合のカウンタと入力途中を全て捨てる', () => {
    const st = useAnnotationStore.getState()
    st.init(1, 11, 2, 23, 14, 8, 'player_b')
    expect(useAnnotationStore.getState().scoreA).toBe(14)
    act(() => useAnnotationStore.getState().clearMatch())
    const s = useAnnotationStore.getState()
    expect(s.matchId).toBeNull()
    expect(s.currentSetId).toBeNull()
    expect(s.currentSetNum).toBe(1)
    expect(s.currentRallyNum).toBe(1)
    expect(s.scoreA).toBe(0)
    expect(s.scoreB).toBe(0)
    expect(s.currentStrokes).toEqual([])
    expect(s.isRallyActive).toBe(false)
  })

  it('保存直前の照合: 別試合の store は拒否し、同じ試合なら許可する', () => {
    expect(isStoreForMatch(1, '2')).toBe(false)
    expect(isStoreForMatch(null, '2')).toBe(false)
    expect(isStoreForMatch(2, undefined)).toBe(false)
    expect(isStoreForMatch(2, '2')).toBe(true)
    expect(isStoreForMatch(2, 2)).toBe(true)
  })
})
