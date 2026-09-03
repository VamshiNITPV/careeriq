/**
 * Fold a string down to a comparable form for searching reference data.
 *
 * Diacritics go first, so "sao paulo" finds São Paulo and "koln" finds Köln.
 * Then punctuation collapses to spaces, so "cote divoire" finds Côte d'Ivoire
 * and "st louis" finds St. Louis.
 *
 * Deliberately not retrofitted into SkillAdder, which compares skill names with
 * a plain toLowerCase(). Sharing it there would change which skills that feature
 * treats as duplicates — a behaviour change to an unrelated feature riding along
 * on a UI refactor.
 */
export function normalizeText(value: string): string {
  return value
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
}
