# Fabrication validator evaluation

Generated 2026-09-14. 50 adversarial cases -- 30 fabrications, 20 honest rewrites -- over three source resumes.

> Labels were written from ADR-012's rule (*any entity in the output and not in the input*) **before** running the validator. Three cases fail and are kept exactly as written; a dataset edited to agree with the implementation is not evidence about it.

## Against the target

| | Result | Target |
|---|---|---|
| **Fabrication recall** | 0.900 | 1.000 |
| **Fabrication recall, excluding known limits** | **1.000** over 27 cases | 1.000 |
| Honest rewrites passed | 1.000 (20/20) | -- |
| Precision of rejections | 1.000 | -- |

ml.md sets exactly one target here, and it is recall. That asymmetry is the design: a missed fabrication puts an unsupportable claim on a resume and surfaces in an interview; a false positive withholds a suggestion the user never sees. The two are not comparable, so they are not averaged into an F1 -- that would let a gain on the cheap side hide a loss on the expensive one.

**Precision is a cost, not a gate.** A validator that rejects everything scores perfect recall and ships nothing. At 20/20 honest rewrites passing, the current version is not doing that.

## What the headline number covers

**1.000 over everything the design claims to catch**, across every evasion in the dataset:

- Inflated metrics (35% -> 40%), including the same claim as digits, as words (*forty percent*), as a scaled unit (*$4M*), and as a derived figure never stated (900KB to 410KB rewritten as *60%*).
- Unit swaps -- the resume's "three junior engineers" does not license *3% growth*. The unit is part of the claim.
- Credentials, both spelled out (*AWS Certified Solutions Architect*) and as acronyms (*CKA*, *PMP*).
- Employers and institutions, mid-sentence, in possessive form, and **sentence-initial**.
- Skills adjacent to real ones -- Docker in the resume, Kubernetes in the suggestion -- and near-miss names (*Java* against a resume saying *JavaScript*).
- Dates: an invented year, a moved range endpoint, a changed month under a real year.

## The three it misses

Reported in the headline rather than excluded from it. A dataset that quietly dropped its hard cases would report a 100% that means nothing.

**1-2. Scope inflation that introduces no new entity.** *"Managed the analytics function"* from a resume that says "Built daily sales reports"; *"Owned the entire billing platform architecture"* from "Rebuilt the billing settings screen". Every word is already in the source, so an entity-level check cannot see it — the invention is in the *relation between* the words, not in any of them.

This is a real gap, and it is the one ADR-012 accepts by construction: catching it means judging whether a rewrite changed the meaning, which is the open-ended language problem an LLM would be needed for. Putting a model back in the safety path is the thing ADR-012 exists to prevent. The mitigation is upstream -- constrain the *generation* so suggestions cannot restructure a claim -- not here.

**3. A lowercase proper noun outside the taxonomy.** *"...at flipkart..."* is missed because capitalisation is the only signal the proper-noun rule has, and Flipkart is an employer rather than a skill so nothing in the taxonomy covers it.

Worth noting how this was found: the dataset's *first* lowercase case used **stripe**, and it was caught — but by the skill check, because Stripe is a taxonomy entry and the matcher is case-insensitive. The case passed for a reason other than the one it was testing. The second case isolates the actual gap. This is the general hazard with adversarial datasets: a case can look covered while the mechanism it targets is untested.

## What this does not measure

The validator only sees a (suggestion, source) pair. It says nothing about **suggestion quality** -- whether a rewrite is an improvement — nor about whether the generation step produces useful candidates at all. Those need the LLM integration and a separate dataset.

It also does not measure behaviour under **prompt injection**, where a resume contains instructions aimed at the model. That is a property of the prompt architecture (ml.md section 6.2) and belongs with the adversarial prompt suite, not here.

## Reproducing

```bash
docker compose run --rm -v "$(pwd)/ml:/ml" backend \
    sh -c 'export PYTHONPATH=/app:/ml; python -m evaluation.run_fabrication_eval'
```

Exits non-zero only on a miss the design claims to cover. A known limit is documented and stays visible in the number rather than turning every future run red.
