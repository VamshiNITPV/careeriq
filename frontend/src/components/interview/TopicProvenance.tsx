import type { TopicSource } from '@/types/interview'

/**
 * Where this interview's questions came from, said plainly.
 *
 * This is the sentence `blueprint.py` has claimed since 9.2 that its
 * `is_generic` flag produced — "so a user is not shown 'based on what employers
 * want' over a generic list". The flag was computed and thrown away; nothing
 * carried it past the function. This is the claim finally being made, or not
 * made, for real.
 *
 * Three sources and three different promises. Collapsing them would put the
 * strongest wording over the weakest case, which is the specific dishonesty the
 * whole change exists to remove.
 */
export function TopicProvenance({
  source,
  postings,
}: {
  source: TopicSource | null
  postings: number | null
}) {
  /*
   * Null renders nothing at all.
   *
   * It means no question has been generated yet — a real state that lasts a few
   * seconds after starting. Any sentence here would be a claim about topics that
   * do not exist, and "we don't have enough postings" is the worst of the
   * available guesses because it is both wrong and discouraging.
   */
  if (source === null) return null

  const count = postings ?? 0

  let text: string
  // The second clause is only said for the two skill-derived sources. GENERIC
  // topics are a fixed list, and the gap ordering has nothing to act on there.
  if (source === 'THIS_JOB') {
    text =
      'Topics come from what the posting you chose asks for, with the things your resume does not cover yet first.'
  } else if (source === 'ROLE_DEMAND') {
    // The number is the evidence. "Based on market demand" with nothing behind
    // it is the kind of claim this line exists to replace.
    text = `Topics come from what ${count} live posting${count === 1 ? '' : 's'} for this role ask for, with the things your resume does not cover yet first.`
  } else if (count === 0) {
    text =
      'No postings for this role in here yet, so these are general topics — still useful, just not specific to anyone hiring.'
  } else {
    // Naming the number matters: "only 2 match" tells somebody the corpus is
    // thin, where "general topics" sounds like a decision we made about them.
    text = `Only ${count} posting${count === 1 ? '' : 's'} here match this role, which is too few to read demand from — so these are general topics.`
  }

  return <p className="text-sm text-slate-500">{text}</p>
}
