# pstack model configuration. One line per role. Delete a line to fall back to the skill default.
# `inherit-parent` or `auto` as a value: the role runs on the parent chat model. Alias entries in a panel list still count toward its fan-out.
# Project-scoped: every role runs on Opus 5.5 (`opus`) at the medium budget.
# Never run Fable in this project, including the poteto-mode fallback after two failed Opus runs. Report the failure to the user instead.
# defaults: 3
# budget: medium (high)
feature, refactoring: opus high
bug-fix: opus high
perf-issue: opus high
hillclimb: opus high
judgment and prose: opus high
arena runners: opus medium, opus medium
arena cross-judge pool: opus medium
swarm workers: opus medium
interrogate reviewers: opus medium
