# Secret Audit Report Format

Write the final report as concise markdown with these sections:

## Scope

- Job id
- Target prefix
- Reason
- Secret keys checked

## Capability Split

Explain which process saw which surface:

- `scout` could read the target prefix but had no `secrets` access
- `verifier` could read evidence and scoped secret keys but not the full target

## Confirmed Live Secret Matches

List only:

- file key
- line or section reference
- secret key name
- why it is confirmed

Never print the secret value.

## Probable Secrets Without Live Match

List suspicious values that still need human review.

## Benign Fixtures Or Placeholders

List obvious examples or fake values so operators can distinguish noise from
real leaks.

## Recommended Actions

Include direct next steps such as rotate, remove from git history, move to the
secret store, or add to fixtures documentation.
