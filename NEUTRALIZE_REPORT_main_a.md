# Neutralization Report - origin/main (range B-(a), conversation 2/11)

Repo: MasayukiTa/shuttle-scope
Worktree: %TEMP%/m365-companion/agents/neutral_a
Branch: neutralize/customer-name-main-a
Base: origin/main = 2b5c795de492ac6b02e1562bf2c807101bb00b28

## Goal-named search actually executed

Command (goal-specified matcher), patterns supplied via -f file to preserve CJK:

    git grep -i -n -f pat.txt    # pat.txt contains the two target tokens

The pattern file contains the Japanese customer token and the English token,
equivalent to: git grep -i -E "<JP-token>|sendai"

### Result against the ORIGINAL tracked tree (this report file excluded)
- Matches in source / tests / markdown / identifiers : 0
- The only matches produced by the matcher are inside THIS report file itself
  (because the report quotes the tokens to describe them). Those are not repo
  content under neutralization scope.

### Cross-check (full-tree byte scan, scan2.py)
- TOTAL_FILES=1881, READ=1881, SKIPPED=0, HITS=0 (bytes -> utf-8/latin-1 decode)

### Cross-check (ja.json touched by prior i18n PR)
- direct content check: no JP customer token, no english token, no youbou token.

## Hit counts
- BEFORE (current origin/main, excluding this report) : 0
- AFTER  : 0
- Residual hits list (repo content) : (none)

## Conclusion
The customer name does NOT appear anywhere in the current origin/main repo
content (prose, comments, docstrings, test titles, markdown, identifiers,
file names). Neutralization was already completed by previously merged commits:
- #370 docs: neutralize customer name in comments and test titles
- #371 fix(i18n): ja.json wording unification
Any occurrence string seen in git LOG is a historical commit MESSAGE only, not
current file content.

Therefore range B-(a) requires no code replacement: the diff is legitimately a
verification-only report. Traceability request numbers (request #N) are preserved.
