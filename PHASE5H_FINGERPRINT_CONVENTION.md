# Phase 5H — Canonical Preregistration Fingerprint Convention

## Root cause

`GENERATION_ORDER_ISSUE`: Phase 5H fingerprints were calculated from exact
UTF-8 document bytes while their registered self-fingerprint field contained
`TO_BE_FILLED_BY_FREEZE_TOOL`, then the placeholder alone was replaced by the
resulting SHA-256. Literal-file SHA therefore necessarily differs afterward.

## Canonical verification

Read exact bytes; require exactly one line matching
`Preregistration fingerprint: \`<64 lowercase hex>\`.`; replace only that
64-character value with literal `TO_BE_FILLED_BY_FREEZE_TOOL`; preserve every
other byte; SHA-256 the result. No whitespace/newline/Markdown/JSON
normalization, semantic parsing, sorting or global hash replacement occurs.

This is the verified original Phase 5H generation procedure and matches the
explicit Phase 5G convention. It is implemented by
`src/fx/research/fingerprints.py`.

Frozen authoritative canonical hashes:

- Cost preregistration: `a3f18e3876bd0b739d21fc5cb30ac722f58c9d8032099ef2d25831b4267b122c`
- Strategy preregistration: `212993340e68c33c78fbb10dbc618c4c10acc6e21ffd81b94faa6571e32fc709`

THIS REMEDIATION CHANGES REPRODUCIBILITY MECHANICS ONLY.

IT DOES NOT CHANGE hypotheses, parameters, costs, temporal splits, candidate
rules, datasets or historical observations. Historical performance had not
been run before this remediation.
