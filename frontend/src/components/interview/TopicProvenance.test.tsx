import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { TopicProvenance } from './TopicProvenance'

describe('TopicProvenance', () => {
  it('names the posting when the topics came from it', () => {
    render(<TopicProvenance source="THIS_JOB" postings={1} />)

    expect(screen.getByText(/the posting you chose/i)).toBeInTheDocument()
  })

  it('says the gaps come first, for both skill-derived sources', () => {
    // Added in 9.7: the ordering lifts what the resume does not cover, and a
    // line describing where topics come from should say so.
    for (const source of ['THIS_JOB', 'ROLE_DEMAND'] as const) {
      const { unmount } = render(<TopicProvenance source={source} postings={5} />)
      expect(screen.getByText(/does not cover yet first/i)).toBeInTheDocument()
      unmount()
    }
  })

  it('does not claim a gap ordering over a generic list', () => {
    // GENERIC topics are a fixed list, so there is no gap to have acted on.
    render(<TopicProvenance source="GENERIC" postings={0} />)

    expect(screen.queryByText(/does not cover yet/i)).not.toBeInTheDocument()
  })

  it('counts the postings when the topics came from demand', () => {
    // The number is the evidence. "Based on market demand" with nothing behind
    // it is the claim this line exists to replace.
    render(<TopicProvenance source="ROLE_DEMAND" postings={12} />)

    expect(screen.getByText(/12 live postings for this role/i)).toBeInTheDocument()
  })

  it('says plainly when there are no postings at all', () => {
    render(<TopicProvenance source="GENERIC" postings={0} />)

    expect(screen.getByText(/no postings for this role in here yet/i)).toBeInTheDocument()
  })

  it('names how few matched when some did', () => {
    // "Only 2 match" tells somebody the corpus is thin. "General topics" alone
    // sounds like a decision we made about them.
    render(<TopicProvenance source="GENERIC" postings={2} />)

    expect(screen.getByText(/only 2 postings here match this role/i)).toBeInTheDocument()
  })

  it('renders nothing at all before the first question exists', () => {
    /*
     * The case this component exists for.
     *
     * Null means no question has been generated yet — a real state lasting a few
     * seconds after starting. Any sentence would be a claim about topics that do
     * not exist, and the GENERIC wording is the worst available guess: both wrong
     * and discouraging.
     */
    const { container } = render(<TopicProvenance source={null} postings={null} />)

    expect(container).toBeEmptyDOMElement()
  })

  it('never claims a posting for a source that is not one', () => {
    // The three wordings must stay distinct. Collapsing them would put the
    // strongest claim over the weakest case.
    for (const source of ['ROLE_DEMAND', 'GENERIC'] as const) {
      const { unmount } = render(<TopicProvenance source={source} postings={3} />)
      expect(screen.queryByText(/the posting you chose/i)).not.toBeInTheDocument()
      unmount()
    }
  })

  it('reads as singular for one posting', () => {
    render(<TopicProvenance source="ROLE_DEMAND" postings={1} />)

    expect(screen.getByText(/1 live posting for this role/i)).toBeInTheDocument()
  })

  it('treats a missing count as none rather than crashing', () => {
    // `topic_postings` is nullable independently of `topic_source`, so this pair
    // is reachable from any older row.
    render(<TopicProvenance source="GENERIC" postings={null} />)

    expect(screen.getByText(/no postings for this role in here yet/i)).toBeInTheDocument()
  })
})
