import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { applicationService } from '@/services/applicationService'
import { SavedJobsPage } from './SavedJobsPage'

const renderPage = () =>
  render(
    <MemoryRouter>
      <SavedJobsPage />
    </MemoryRouter>,
  )

describe('SavedJobsPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('carries both lists', async () => {
    // They live on one page because a row crosses between them when "I have
    // applied" is ticked — split across two routes it would appear to vanish.
    vi.spyOn(applicationService, 'list').mockResolvedValue({ items: [], total: 0 })
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Saved', level: 2 })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Applications', level: 2 })).toBeInTheDocument()
  })

  it('titles the page without repeating its own section heading', async () => {
    // The h1 is "Saved jobs" and the section below it is "Saved". Identical
    // text in both would stack two headings that say the same thing, and make
    // a name-based heading query ambiguous.
    vi.spyOn(applicationService, 'list').mockResolvedValue({ items: [], total: 0 })
    renderPage()

    expect(screen.getByRole('heading', { name: 'Saved jobs', level: 1 })).toBeInTheDocument()
    await screen.findByRole('heading', { name: 'Saved', level: 2 })
  })
})
