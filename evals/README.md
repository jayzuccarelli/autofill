# evals

Measures the one thing that caps how well autofill can ever do: whether
`retrieve()` puts the facts a form asks for into the context the browser agent
sees. A fact that is not in that string cannot be filled in correctly no matter
how good the model is.

## Run

```bash
uv run python -m evals.run                  # score at the shipped retrieval_n
uv run python -m evals.run --sweep          # and at larger top-n
uv run python -m evals.run --min-recall 1.0 # exit non-zero below the floor
```

No API key and no network, once Chroma has cached its embedding model. The
first run downloads about 80 MB to `~/.cache/chroma`. Each run takes a few
seconds: it builds a throwaway Chroma index per fixture in a temp directory and
deletes it afterwards.

Not wired into CI, for that download's sake. Run it by hand when you touch
chunking, retrieval, or the `Config` fields either one reads.

## What it reports

Every fact is scored into one of three buckets, which is the useful part: a
miss tells you *which layer* to go fix.

| Bucket | Meaning | Where the fix is |
|---|---|---|
| Found | the fact is in the retrieved context | nothing to do |
| Lost to ranking | the fact is in a chunk, but that chunk was not in the top-n | `retrieval_n` or `retrieval_query` |
| Lost to chunking | the fact is in no single chunk | `chunk_size` or `chunk_overlap` |

## Fixtures

Three synthetic profiles under `fixtures/`, all invented, none real:

- `minimal.md`, a short profile that fits in a single chunk
- `standard.md`, a mid-career resume of the shape most users will have
- `long.md`, an eighteen-year senior profile with the sections that get pushed
  out of a small top-n

`long.md` is the one that earns its keep. At `retrieval_n = 5` it scored 82%,
silently dropping highest degree, doctoral school, skills, open source,
publications, and referral source. That is what moved the default to 10.

## Adding a case

Append a `Case` to `CASES` in `cases.py`: the fixture name, the label a real
form would use, and a regex for the value. Patterns are matched after
whitespace is collapsed to single spaces, so write them as if the markdown were
not hard-wrapped.

To add a whole profile, drop `fixtures/<name>.md` and write cases against it.
`run.py` picks up any fixture that has at least one case.
