# Secret Audit Heuristics

Use these signals when deciding whether a file probably contains a secret.

## Strong positive signals

- File names like `.env`, `.pem`, `.key`, `credentials`, `secrets`, `id_rsa`
- Lines containing:
  - `BEGIN PRIVATE KEY`
  - `BEGIN OPENSSH PRIVATE KEY`
  - `AKIA`
  - `ghp_`
  - `github_pat_`
  - `sk-`
  - `xoxb-`
  - `postgres://`
  - `mongodb+srv://`
  - `Authorization: Bearer`
- Long single-line tokens assigned to keys named `token`, `secret`, `password`,
  `api_key`, `client_secret`, or `webhook`

## False-positive hints

- Values containing words from `placeholder_markers` in `config.json`
- Example snippets in markdown docs or comments
- Values clearly labeled as fake, sample, mock, or local-only
- Test fixtures with intentionally invalid prefixes

## Evidence hygiene

- The final report must not include raw secret values.
- Evidence artifacts may include the raw candidate value only when needed for a
  verifier process to compare against a live secret.
- Never copy an entire multi-line key block into the report. Summarize it as
  `private-key-block` and keep the artifact internal to the app.
