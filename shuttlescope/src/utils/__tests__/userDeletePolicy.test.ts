import { describe, it, expect } from 'vitest'
import { canShowDeleteButton } from '../userDeletePolicy'

// backend routers/auth.py delete_user と同じ規則を固定する
describe('canShowDeleteButton', () => {
  it('自分自身の行には出さない', () => {
    expect(canShowDeleteButton({ id: 5, is_test: true }, 5, true)).toBe(false)
  })

  it('承認済みの実ユーザ (検証用でも承認待ちでもない) には出さない', () => {
    expect(canShowDeleteButton({ id: 6, is_test: false, awaiting_admin_approval: false }, 5, true)).toBe(false)
    expect(canShowDeleteButton({ id: 6 }, 5, true)).toBe(false)
  })

  it('検証用ユーザと承認待ちユーザには出す', () => {
    expect(canShowDeleteButton({ id: 6, is_test: true }, 5, true)).toBe(true)
    expect(canShowDeleteButton({ id: 7, is_test: false, awaiting_admin_approval: true }, 5, true)).toBe(true)
  })

  it('admin 以外には出さない', () => {
    expect(canShowDeleteButton({ id: 6, is_test: true }, 5, false)).toBe(false)
  })
})
