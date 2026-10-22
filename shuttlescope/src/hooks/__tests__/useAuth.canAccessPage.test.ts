import { describe, expect, it } from 'vitest'
import { canAccessPage } from '../useAuth'

describe('canAccessPage', () => {
  it('is false without a role', () => {
    expect(canAccessPage(null, ['llm'], 'llm')).toBe(false)
  })

  it('admin sees every page', () => {
    expect(canAccessPage('admin', [], 'llm')).toBe(true)
    expect(canAccessPage('admin', [], 'prediction')).toBe(true)
  })

  it('analyst and coach see the LLM page only with a real llm grant', () => {
    expect(canAccessPage('analyst', [], 'llm')).toBe(false)
    expect(canAccessPage('coach', ['prediction', 'expert_labeler'], 'llm')).toBe(false)
    expect(canAccessPage('analyst', ['llm'], 'llm')).toBe(true)
    expect(canAccessPage('coach', ['llm'], 'llm')).toBe(true)
  })

  it('analyst and coach keep the other pages without a grant list', () => {
    expect(canAccessPage('analyst', [], 'prediction')).toBe(true)
    expect(canAccessPage('coach', [], 'expert_labeler')).toBe(true)
  })

  it('player and llm roles follow their grants', () => {
    expect(canAccessPage('player', [], 'prediction')).toBe(false)
    expect(canAccessPage('player', ['prediction'], 'prediction')).toBe(true)
    expect(canAccessPage('llm', ['llm'], 'llm')).toBe(true)
  })
})
