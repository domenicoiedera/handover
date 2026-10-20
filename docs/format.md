# Packet format (`handover:v1`)

One JSON document. Canonical form: `json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` encoded as UTF-8. The seal is `sha256(canonical(body_without_seal))`.

```json
{
  "format": "handover:v1",
  "created_at": "2026-10-20T19:03:46Z",
  "repo": { "head": "<40 hex or null>", "branch": "main", "dirty": 0 },
  "facts": [
    { "text": "what is asserted, in prose",
      "claims": [ { "kind": "file", "path": "src/app.py", "sha256": "<64 hex>" } ] }
  ],
  "decisions": [ { "text": "what was decided", "why": "optional reason" } ],
  "open":      [ { "text": "what is unfinished", "owner": "optional owner" } ],
  "owners":    [ { "seat": "optional name", "paths": ["src/**"] } ],
  "seal": { "alg": "sha256", "value": "<64 hex>" }
}
```

`repo.dirty` is `null` when git could not answer - never `0` by default.

## Claims

| kind | required fields | checked by |
|------|-----------------|------------|
| `file` | `path`, `sha256` (filled by capture) | reading the bytes |
| `absent` | `path` | `Path.exists()` |
| `text` | `path`, `contains` | substring search in the file |
| `git` | `ref`, `sha` (filled by capture) | `git rev-parse --verify <ref>^{commit}` |

Each claim evaluates to one of:

- `OK` - the claim holds.
- `STALE` - it was true at capture and is no longer.
- `MISSING` - the thing it points at is gone.
- `UNKNOWN` - it could not be evaluated (unreadable file, no usable hash, no git). **Unknown counts as failure.**

## Verdicts

| verdict | meaning | `check` exit |
|---------|---------|--------------|
| `VERIFIED` | at least one claim, and all of them `OK` | 0 |
| `STALE` | at least one claim is not `OK` | 1 |
| `UNCHECKED` | zero claims | 1 |
| `UNTRUSTED` | malformed packet or `SEAL-INVALID` | 1 (seal) / 2 (malformed) |

## Source spec (input to `capture`)

Same shape, minus `format`, `created_at`, `repo` and `seal`. `sha256` and `sha` may be omitted; capture reads them from the tree. If they are present, capture keeps them and refuses the packet when they no longer match.

## Compatibility

`format` is versioned. A future `handover:v2` will be read by a v2 binary only; v1 packets stay readable by v1. No silent upgrades.
