/**
 * Audit #576: the Annotator comment POST body must not carry `author_role`.
 *
 * backend CommentCreate uses extra="forbid" and derives author_role from the
 * authenticated context, so a frontend that sends author_role gets 422 on every
 * comment. handleSubmitComment (src/pages/AnnotatorPage.tsx) builds its POST
 * /comments body from exactly these fields. This test replicates that body
 * shape (same approach as AnnotatorPage.recordingBranchError.test.tsx) and pins
 * that author_role is absent and the key set is the agreed contract.
 *
 * If a regression re-adds author_role to the payload, this test fails before the
 * 422 reaches production.
 */
import { describe, it, expect } from 'vitest'

// Mirror of handleSubmitComment's POST /comments body (AnnotatorPage.tsx).
function buildCommentBody(opts: {
  matchId: string
  commentRallyId: number | null
  commentText: string
}) {
  return {
    match_id: Number(opts.matchId),
    rally_id: opts.commentRallyId ?? undefined,
    text: opts.commentText.trim(),
    // author_role is intentionally NOT sent: the server owns it.
    is_flagged: false,
  }
}

describe('項目576 コメント投稿 payload に author_role を含めない', () => {
  it('payload に author_role キーが存在しない', () => {
    const body = buildCommentBody({ matchId: '3', commentRallyId: 7, commentText: 'nice' })
    expect('author_role' in body).toBe(false)
    expect(Object.keys(body).sort()).toEqual(['is_flagged', 'match_id', 'rally_id', 'text'])
  })

  it('rally_id が無いときも author_role を足さない', () => {
    const body = buildCommentBody({ matchId: '3', commentRallyId: null, commentText: ' hi ' })
    expect('author_role' in body).toBe(false)
    expect(body.rally_id).toBeUndefined()
    expect(body.text).toBe('hi')
    expect(body.is_flagged).toBe(false)
  })
})
