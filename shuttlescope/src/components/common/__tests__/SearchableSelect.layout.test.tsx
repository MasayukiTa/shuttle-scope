/**
 * SearchableSelect レイアウト契約 (UI点検 B-1)
 *
 * 以前は右側の suffix（「（DEMO…） [12試合]」）が shrink-0 で、名前 span が
 * 27px しか残らず「選…」のように 1 文字へ切れていた。
 * jsdom はレイアウトを計算できないので、「名前は縮めず suffix が先に省略される」
 * ことを class / 構造で固定する:
 *   - 名前: shrink-0 + max-w-full + truncate (名前は縮まない。長すぎるときだけ全幅で省略)
 *   - suffix: min-w-0 + truncate かつ shrink-0 を持たない (先に消える)
 *   - 全文は title で確認できる
 */
import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { SearchableSelect } from '../SearchableSelect'

const options = [
  { value: 1, label: '標本 桃子', suffix: '（DEMO 大学チーム） [12試合]' },
  { value: 2, label: '標本 太郎', suffix: '（DEMO 大学チーム） [3試合]' },
]

// jsdom には scrollIntoView が無い (ハイライト行のスクロールで呼ばれる)
Element.prototype.scrollIntoView = () => {}

function classes(el: Element | null): string[] {
  return (el?.getAttribute('class') ?? '').split(/\s+/)
}

describe('SearchableSelect: 名前最優先レイアウト', () => {
  it('トリガー: 名前は shrink-0 / max-w-full、suffix は先に縮む (shrink-0 でない)', () => {
    const { container } = render(<SearchableSelect options={options} value={1} onChange={() => {}} />)
    const name = container.querySelector('button [data-ss-name]')
    const suffix = container.querySelector('button [data-ss-suffix]')
    expect(name?.textContent).toBe('標本 桃子')
    expect(classes(name)).toEqual(expect.arrayContaining(['shrink-0', 'max-w-full', 'truncate']))
    expect(suffix?.textContent).toContain('[12試合]')
    expect(classes(suffix)).toEqual(expect.arrayContaining(['min-w-0', 'truncate']))
    expect(classes(suffix)).not.toContain('shrink-0')
  })

  it('トリガー: 省略されても全文を title で確認できる', () => {
    const { container } = render(<SearchableSelect options={options} value={1} onChange={() => {}} />)
    const holder = container.querySelector('button span[title]')
    expect(holder?.getAttribute('title')).toBe('標本 桃子 （DEMO 大学チーム） [12試合]')
  })

  it('ドロップダウンの行: 名前 shrink-0 / suffix は縮む、行ごとに title で全文', () => {
    const { container } = render(<SearchableSelect options={options} value={null} onChange={() => {}} />)
    fireEvent.click(container.querySelector('button') as HTMLElement)
    const rows = container.querySelectorAll('[data-option]')
    expect(rows).toHaveLength(2)
    const row = rows[0]
    expect(row.getAttribute('title')).toBe('標本 桃子 （DEMO 大学チーム） [12試合]')
    const name = row.querySelector('[data-ss-name]')
    const suffix = row.querySelector('[data-ss-suffix]')
    expect(classes(name)).toEqual(expect.arrayContaining(['shrink-0', 'max-w-full', 'truncate']))
    expect(classes(suffix)).toEqual(expect.arrayContaining(['min-w-0', 'truncate']))
    expect(classes(suffix)).not.toContain('shrink-0')
  })

  it('suffix なしでも名前は出る / 選択は従来どおり動く', () => {
    let picked: unknown = null
    const { container } = render(
      <SearchableSelect options={[{ value: 5, label: '名前のみ' }]} value={null} onChange={(v) => { picked = v }} />,
    )
    fireEvent.click(container.querySelector('button') as HTMLElement)
    fireEvent.click(screen.getByText('名前のみ'))
    expect(picked).toBe(5)
  })
})
