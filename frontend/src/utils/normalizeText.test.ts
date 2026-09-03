import { describe, expect, it } from 'vitest'
import { normalizeText } from './normalizeText'

describe('normalizeText', () => {
  it('strips diacritics', () => {
    expect(normalizeText('São Paulo')).toBe('sao paulo')
    expect(normalizeText('Köln')).toBe('koln')
    expect(normalizeText("Côte d'Ivoire")).toBe('cote d ivoire')
  })

  it('lowercases', () => {
    expect(normalizeText('INDIA')).toBe('india')
  })

  it('collapses punctuation and whitespace to single spaces', () => {
    expect(normalizeText('St. Louis')).toBe('st louis')
    expect(normalizeText('New   York')).toBe('new york')
    expect(normalizeText('  Pune  ')).toBe('pune')
  })

  it('keeps digits', () => {
    expect(normalizeText('Region 12')).toBe('region 12')
  })

  it('returns an empty string for punctuation only', () => {
    expect(normalizeText('---')).toBe('')
  })
})
