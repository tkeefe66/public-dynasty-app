# Safe continued development

Develop from the current public `main` or a branch descended from it. The older local
repository contains private history: retain it as a private archive, not a branch to
merge, force-push or mirror into this repository. Transfer individual reviewed changes
without importing its ancestry. Keep unrelated draft files out of publication commits.

## Local checks

Install Python 3.11+, Gitleaks 8.30.1+ and pre-commit, then run `pre-commit install`.
The hook scans indexed bytes, so unstaged edits cannot conceal staged content. Missing
Gitleaks blocks the check. CI runs the same checker over the complete proposed index.

For private identifier checks, create an owner-readable file **outside the working
tree** with one literal value per line, then configure this clone:

```sh
chmod 600 /absolute/private/location/patterns.txt
git config --local publication.privatePatternsFile /absolute/private/location/patterns.txt
```

Never commit this file, put its real values into a tracked hook configuration, or print
matches. The checker reports only affected paths. Once configured, an absent/empty or
insecurely permissioned pattern file blocks the check. Without local configuration,
the checker explicitly reports that it performs only general secret scanning. CI does
not receive the private identifier list. Hooks can be bypassed and neither check
recognizes every kind of personal information; review prose and images before publishing.

Run `python3 scripts/check_publication.py --all` before a release. The check covers
current indexed content, not all historical commits or GitHub-hosted artifacts. Run
`public-repo-readiness` for a publication review after changing integrations, importing
real data or broadening the publication scope.

## Historical content

Removing a file in a new commit does not remove it from earlier published commits.
This cleanup preserves existing history; historical personal notes remain a separate
exposure to resolve deliberately. No history rewrite or repository deletion is implied.
