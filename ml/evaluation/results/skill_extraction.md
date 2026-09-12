# Skill extraction evaluation

Generated 2026-09-12T10:48:57.785095+00:00. 30 job postings, 511 hand-written gold labels, against a taxonomy of 319 skills.

> Labels are Claude-written and pending human review. A weaker caveat than on the matching dataset: "does this posting name Kubernetes" has an answer a second reader can check against the text, unlike a relevance judgement.

## Against the targets

| | Precision | Recall | F1 |
|---|---|---|---|
| **Shipped extractor** | 0.703 | 0.949 | 0.808 |
| Naive lookup (baseline) | 0.719 | 0.772 | 0.745 |
| _ml.md target_ | 0.85 | 0.80 | 0.82 |

Micro-averaged: pooled over every document, so a posting naming forty skills counts for more than one naming four. The macro average is in the JSON.

### Read the precision figure carefully — it is not what it looks like

**It is not a hallucination rate.** Checked term by term, roughly four in five counted false positives are words *literally present in the posting*: Security appears in all ten postings it was penalised for, Deployment in seven of seven, Scalability in seven of seven. The extractor is not inventing them.

What it is measuring is a genuine disagreement about what counts as a skill. A posting saying *"optimize application performance, scalability, and security"* is describing the work, not listing requirements — and the gold labels treat it that way, while the taxonomy holds `Security`, `Scalability`, `Deployment` and `Software Engineering` as entries the matcher dutifully fires on. **The extractor has no way to tell "the job involves security" from "security is a required skill"**, because both land in a RESPONSIBILITIES block, which maps to REQUIRED at 0.80 confidence.

This is the same defect Phase 6.5 hit from the other side, where `Communication` turned up in 45% of postings and flattened the skill dimension of the ranking. Rarity weighting treated the symptom; this is the cause.

**So: the precision number is honest about the system's output and unreliable as a verdict on the matcher.** Splitting the two needs either a taxonomy without generic entries, or gold labels with a sharper rule than the one used here, and that is the next piece of work rather than something to paper over now.

## The recall ceiling

**36 of 511 gold skills (7%) are not in the taxonomy at all.** No matcher change can find them; only adding entries can. That share caps recall, and it is reported separately so a recall figure is never read as a verdict on the matching code when it is really a verdict on the word list.

Most frequently missing:

| Skill | Postings |
|---|---|
| monitoring | 4 |
| GPU | 2 |
| artificial intelligence | 2 |
| async programming | 2 |
| cloud computing | 2 |
| data engineering | 2 |
| data warehousing | 2 |
| distributed computing | 2 |
| Big Data | 1 |
| ISDN | 1 |
| SRE | 1 |
| TCP/UDP | 1 |
| analytical skills | 1 |
| attention to detail | 1 |
| data integration | 1 |

## Where it goes wrong

| False positive | Postings |
|---|---|
| Security | 10 |
| Software Testing | 8 |
| Deployment | 7 |
| Performance Optimization | 7 |
| Scalability | 7 |
| Software Engineering | 6 |
| Technical Documentation | 6 |
| Leadership | 5 |
| Mentoring | 5 |
| Teamwork | 5 |
| Backend Development | 4 |
| Caching | 4 |

| Missed (in taxonomy) | Postings |
|---|---|
| Debugging | 2 |
| Embeddings | 2 |
| Prompt Engineering | 2 |
| REST API | 2 |
| Amazon SageMaker | 1 |
| Communication | 1 |
| Database Design | 1 |
| FAISS | 1 |
| Hugging Face | 1 |
| Keras | 1 |
| LangChain | 1 |
| LangGraph | 1 |

