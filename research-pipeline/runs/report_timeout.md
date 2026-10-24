# Findings report: US work from home, hybrid retention, and office demand

Research question: "How much US work is done from home, and what do hybrid schedules do to retention and office demand?"

Input file: /home/james/Coding Projects/agent-demos/research-pipeline/runs/findings.md

## Established

**hybrid_attrition: 33%**

Attrition is 33% lower under hybrid schedules than in the office comparison. Two sources support this:

- https://fake-sources.example/hybrid-trial-2024 (published 2024-06-10). Excerpt: "Employees assigned to hybrid schedules quit 33% less often than the office group."
- https://fake-sources.example/retention-review-2025 (published 2025-02-14). Excerpt: "Pooled estimates show a 33% reduction in attrition under hybrid schedules."

## Contested

**wfh_share: share of paid full days in the US worked from home**

| Value | Reference year | Source URL | Published | Excerpt |
|---|---|---|---|---|
| 28% | 2022 | https://fake-sources.example/wfh-research-2023 | 2023-01-20 | "Across 2022, 28% of paid full days in the US were worked from home." |
| 22% | 2024 | https://fake-sources.example/census-pulse-2025 | 2025-04-02 | "In 2024, 22% of paid full days in the US were worked from home." |

The excerpts state one difference: the two figures cover different years (2022 and 2024).

One more difference appears only in the findings file's claim text for the 22% figure, which says "counting paid days only and excluding self-employed respondents." That wording is not in the quoted excerpt, so the excerpts do not confirm it as a methodological difference.

## Single source

**lease_footprint: 14% (unconfirmed)**

- The median renewed office lease footprint was 14% smaller than the same tenant's pre-2020 lease. Source: https://fake-sources.example/lease-trends-2024 (published 2024-11-05). Excerpt: "Median renewed lease footprint shrank 14% against the pre-2020 lease."

## Coverage gaps

- **office-vacancy-2025**: transient error, "source office-vacancy-2025 timed out after 2.0s".
  - **What this leaves unanswered:** the "office demand" part of the question. No office vacancy data was retrieved, so the only office-demand evidence is the single-source lease footprint figure above, which is unconfirmed.