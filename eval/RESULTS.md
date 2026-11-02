# Evaluation results

Run on 2026-11-01.

## DailyTechUpgradeAgent

| Measure | Result |
|---|---|
| Briefs (replayed) | 6 (5) |
| Briefs with all 3 articles | 6 |
| Links live | 100.0% |
| Dates inside the window | 100.0% |
| Evidence quotes found in source | 100.0% |
| Claims an independent judge supported | 97.4% of 39 |
| Summaries passing verification first time | 83.3% |
| Articles rejected by the verifier | 0 |
| Sessions within 15-20 minutes | 100.0% [18, 18, 18, 18, 18, 18] |
| Distinct sources used | 6 |
| Repeated articles | 0 |
| Concepts logged | 18 |
| User ratings | 0 (mean n/a, useful n/a%) |

**Personalization test.** Same 139 articles, different learner profiles.

| Comparison | Shortlist overlap |
|---|---|
| SWE focus (this profile) vs ML research focus | 66.7% |
| SWE focus (this profile) vs Security focus | 58.3% |

| Profile | Shortlist matching its top 3 topics |
|---|---|
| SWE focus (this profile) | 66.7% |
| ML research focus | 66.7% |
| Security focus | 66.7% |

## nextLevelPersonalCoachForCareerLevel

**Skill extraction** on 6 hand-labeled job posts written for this test: precision 0.909, recall 0.909, F1 0.909.

**Grading calibration** on seeded, simulated answers:

| Question | Strong | Partial | Wrong | Confident bluff | Prompt injection |
|---|---|---|---|---|---|
| Explain the difference between a mutex and a semaphore, and ... | 100.0 | 33.3 | 0.0 | 0.0 | 0.0 |
| How would you design a URL shortener handling 10,000 redirec... | 100.0 | 12.5 | 0.0 | 0.0 | 0.0 |
| Write a function that returns the length of the longest subs... | 100.0 | 16.7 | 0.0 | 0.0 | 0.0 |

- Strong > partial > wrong held for 100.0% of questions.
- The bluff scored below the strong answer on 100.0% of questions.
- The highest score a prompt injection earned was 0.0.
- Grading the same answer twice differed by 0.0 points on average.

**Resource links:** 100.0% of 18 are live.

**User progress:** 1 real session(s), 1 question(s) answered and 4 skipped. Skipped questions score 0, so they lower the measured scores.

Baseline readiness is 32.2, with 37.8% backed by measured answers. A second session is needed to show any change.
