import { describe, expect, it } from 'vitest'
import { buildExpertLabelRequest } from '../expertLabelPayload'

describe('buildExpertLabelRequest', () => {
  it('sends exactly the keys the backend LabelPayload accepts', () => {
    const body = buildExpertLabelRequest('7', 42, 'coach', {
      posture_collapse: 'minor',
      weight_distribution: 'center',
      shot_timing: 'optimal',
      confidence: 3,
      comment: 'ok',
    })
    expect(Object.keys(body).sort()).toEqual([
      'annotator_role',
      'comment',
      'confidence',
      'match_id',
      'posture_collapse',
      'shot_timing',
      'stroke_id',
      'weight_distribution',
    ])
    expect(body.match_id).toBe(7)
  })
})
