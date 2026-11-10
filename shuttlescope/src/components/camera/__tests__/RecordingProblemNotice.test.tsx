import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { RecordingProblemNotice } from '../RecordingProblemNotice'

describe('RecordingProblemNotice', () => {
  it('shows nothing while recording is idle or healthy', () => {
    const { container, rerender } = render(<RecordingProblemNotice state="idle" errorMsg={null} />)
    expect(container).toBeEmptyDOMElement()
    rerender(<RecordingProblemNotice state="recording" errorMsg={null} />)
    expect(container).toBeEmptyDOMElement()
    rerender(<RecordingProblemNotice state="completed" errorMsg={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows an alert with the reason when the recording failed', () => {
    render(<RecordingProblemNotice state="error" errorMsg="finalize failed: 500" />)
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('録画に問題があります')
    expect(alert).toHaveTextContent('finalize failed: 500')
  })

  it('shows an alert when chunks were lost even though the recording completed', () => {
    render(<RecordingProblemNotice state="completed" errorMsg="chunk loss: dropped=2 stillPending=0" />)
    expect(screen.getByRole('alert')).toHaveTextContent('chunk loss: dropped=2')
  })
})
