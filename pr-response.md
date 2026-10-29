# PR Response Doc — CineLog Watchlist Feature

Responses to the six review comments from `@dev-lead` on the watchlist PR.

---

## AI Usage

I used Claude Code (Opus) throughout this project, and it did a substantial
share of the work: reading the codebase, implementing the code changes,
drafting these responses, and driving the rebase. I am recording that plainly
rather than understating it.

Where it was genuinely useful:

- **Codebase orientation.** Before reading any review comment, I had it
  summarise `services/collection_service.py` and `tests/test_collection.py`
  and identify the conventions the project follows. That surfaced the
  `verb_to_noun` naming rule and the `FilmNotFoundError` / `AlreadyIn*Error`
  exception pattern, which is what Comments 1 and 2 are really asking me to
  follow.
- **Finding every call site.** For Comment 1 I had it run a project-wide
  search rather than trusting my memory of where the function was used. It
  found exactly three references — the definition, the import, and the call —
  matching what the reviewer said to expect.
- **Verifying the test actually discriminates.** When I wrote the sort-order
  test, I asked whether the fixture could pass under both an alphabetical and
  a date-added sort. It could have, so I changed the fixture titles to run
  opposite to insertion order. That is the kind of mistake that produces a
  test which passes for the wrong reason.

Where I had to override it or verify by hand:

- **The design decisions in Comments 4 and 5 are mine.** I drafted the
  positions first and then used the AI as a devil's advocate — "what would a
  careful reviewer say against this?" The counterargument it raised against
  private-by-default was the cold-start problem for a discovery feature, which
  was real and which I have now acknowledged explicitly in the tradeoff
  section rather than ignoring.
- **The rebase conflict resolution required reading both sides.** The naive
  resolution is to take `main`'s version wholesale. That would have silently
  dropped the `index=True` my branch added to `WatchlistEntry.film_id`. I
  resolved it by hand to keep both the UUID type from `main` and the index
  from this branch.
- **Scope discipline on the UUID sweep.** A search for integer references
  returns `Film.year` and `CollectionEntry.rating` alongside the real film-ID
  references. Those are integers by design. Changing them because they matched
  a grep would have been wrong.

---

## Comment 1 — Rename

> `save_to_watchlist()` should follow the project's naming convention. Compare
> with `add_to_collection()` — the pattern here is `verb_to_noun`. Please
> rename to `add_to_watchlist()` and update all call sites.

**What I did:** Renamed `save_to_watchlist()` to `add_to_watchlist()` in
`services/watchlist_service.py` and updated both call sites in
`routes/watchlist/watchlist.py` — the import on line 8 and the invocation
inside `add_film()`. I also changed the function's docstring from "Save a
film..." to "Add a film..." so the prose matches the name.

**How I verified:** Ran a project-wide search for `save_to_watchlist` before
renaming, which returned three hits (definition, import, call). After the
rename the same search returns nothing, and a search for `add_to_watchlist`
returns those same three locations. The test suite stayed green.

---

## Comment 2 — Deduplication

> What happens if a user calls this with a film that's already on their
> watchlist? The current implementation would add a duplicate entry. Please
> handle this case.

**What I did:** Followed the pattern in `add_to_collection()`. That function
queries for an existing `(user_id, film_id)` row and raises
`AlreadyInCollectionError` if one is found, rather than inserting. I added an
`AlreadyInWatchlistError` to `services/watchlist_service.py` and the same
`.filter_by(user_id=user_id, film_id=film_id).first()` guard to
`add_to_watchlist()`.

Following the pattern properly meant changing the route as well.
`routes/collection.py` maps `FilmNotFoundError` to 404 and
`AlreadyInCollectionError` to 409. The watchlist route caught neither — so
before this change, adding a film that does not exist produced a 500 rather
than a 404. The watchlist route now has the same `try`/`except` structure and
the same status codes.

Worth noting for the record: `CollectionEntry` enforces this at the schema
level too, with `UniqueConstraint("user_id", "film_id")`. `WatchlistEntry` has
no equivalent constraint. The service-level check resolves the reported
behaviour, but a concurrent double-submit could still create two rows. Adding
the constraint is a migration, which felt out of scope for a review fix — I am
flagging it rather than silently leaving it.

**How I verified:** Added `test_add_to_watchlist_duplicate_raises`, which adds
the same film twice, asserts `AlreadyInWatchlistError` is raised, and then
asserts exactly one row persists. The row count is the part that matters — an
exception could be raised after a successful insert and the test would still
pass without it.

---

## Comment 3 — Missing test

> Please add a test for the case where `film_id` doesn't exist in the
> database. Look at the existing tests in `test_collection.py` — the pattern is
> there.

**What I did:** Created `tests/test_watchlist.py` and wrote
`test_add_to_watchlist_nonexistent_film_raises`, modelled directly on
`test_add_to_collection_nonexistent_film_raises`. I reused the same three
fixtures (`app` with an in-memory SQLite database, `sample_user`,
`sample_film`) and the same `pytest.raises` assertion style, so the two suites
read the same way.

The test passes a UUID sentinel (`"00000000-0000-0000-0000-000000000000"`)
that is not in the database and asserts `FilmNotFoundError` is raised — not a
database integrity error, which is the distinction the collection test is
drawing.

**How I verified:** `pytest tests/test_watchlist.py -v` passes, and the full
suite `pytest tests/ -q` is green at 11 passed.

---

## Comment 4 — Default visibility

> I notice watchlists default to `public=True`. We don't have a documented
> decision on default visibility for user lists. Before I can approve this, I
> need you to add a note to your PR description explaining your reasoning.

**My position:** Watchlists should default to **private**. I have changed
`WatchlistEntry.public` to `default=False` and added an explicit `public`
parameter to `add_to_watchlist()` so callers set visibility deliberately
rather than inheriting whatever the column default happens to be.

**Reasoning:** A default is a decision made on behalf of every user who never
opens a settings page, which is most of them. So the question is not "which
value is better" but "which mistake is cheaper to make."

The costs are not symmetric. A user who wanted their watchlist public and
finds it private loses some discovery, and fixes it with one toggle the moment
they notice. A user who wanted it private and finds it public has already
disclosed something before they knew there was a choice. That disclosure
cannot be undone by flipping the setting afterwards — the data was visible
while it was visible.

The optimisation target is therefore the user who never touches the setting at
all. For that user, private-by-default fails quietly and recoverably, and
public-by-default fails invisibly and permanently.

There is also a signal already in our own schema. `CollectionEntry` has no
`public` column at all; `WatchlistEntry` is the only one of the two that
carries a visibility flag. Someone on this team already concluded that
watchlists raise a visibility question that collections do not — which tracks,
because a collection is a record of what you have watched, while a watchlist
is a statement of intent about what you have not. Intent tends to be the more
revealing of the two.

**Tradeoff acknowledged:** This genuinely hurts the product. CineLog is a
community app, and a discovery feature built on public watchlists is worth
roughly nothing if almost nobody's watchlist is public. Opt-in rates for
settings like this are low, so private-by-default likely means the social
surface of this feature starts near zero and stays there. I am trading
measurable engagement for consent, and I do not want to pretend that trade is
free.

What I would propose instead of reverting the default: prompt once, at the
point a user creates their first watchlist entry, asking whether they want
watchlists public. That recovers most of the discovery value while keeping the
choice with the person whose data it is. The `public` parameter added here is
what such a prompt would call into.

If you would rather keep `public=True`, reverting is a one-line change to the
column default and the parameter's default — but I would want that decision
documented in this file either way, which I think was your actual point.

---

## Comment 5 — Sort order

> I'd prefer watchlists to default to "date added" order rather than
> alphabetical. Most users want to see what they added recently. I'm open to
> discussion if you see it differently — but let's make a decision and document
> it.

**My position:** Agreed — `get_watchlist()` now orders by
`WatchlistEntry.date_added` descending. I am not just deferring, though; I
think there is a stronger reason for it than the one given.

**Reasoning:** The argument offered is about user preference ("most users want
to see what they added recently"), which I suspect is true but which neither
of us has data for. The argument I would actually defend is about consistency
and about what the two lists are *for*.

`get_collection()` already sorts by `date_added` descending, and its docstring
says so explicitly. Shipping a watchlist that sorts alphabetically would mean
CineLog has two list views, side by side, that order themselves by different
keys for no reason the user can see. That is a thing users have to learn, and
learning it buys them nothing.

Beyond consistency: alphabetical ordering optimises for *lookup* — you sort a
catalogue alphabetically because someone arrives knowing the title they want.
Recency ordering optimises for *selection* — you sort a queue by recency
because someone arrives not knowing what they want and needs a short list to
choose from. A watchlist is a queue. People open it to decide what to watch
tonight, not to confirm whether *Arrival* is on it.

**Engagement with your point:** Where alphabetical had real merit, and where
this change costs us something: on a long watchlist — say a few hundred
entries built up over years — recency ordering buries old entries
permanently. A film added in 2023 sits below everything added since and is
effectively invisible, which is a bad outcome for a list whose entire purpose
is "things I still mean to watch." Alphabetical at least gives every entry a
stable, predictable position you can scan to.

I still think recency is the right default, because the long-watchlist user is
the minority case and the cost shows up only at the tail. But the real fix for
that user is explicit sort controls on the list view, not an alphabetical
default that makes the common case worse to help the uncommon one. I would
file that as follow-up work rather than fold it into this PR.

I kept the `.join(Film)` in the query even though ordering no longer needs it.
It preserves the inner-join semantics, so an entry whose film row has gone
missing cannot reach `entry.film.to_dict()` and raise an `AttributeError`.

---

## Comment 6 — Rebase

> A refactor merged to `main` that changed film IDs from integers to UUIDs.
> Your watchlist code still references integer IDs. Please rebase on `main` and
> update accordingly.

**What conflicted:** One conflict, in `models.py`, on the
`WatchlistEntry.film_id` column.

```
<<<<<<< HEAD (main)
    film_id = db.Column(db.String(36), db.ForeignKey("film.id"), nullable=False)
=======
    film_id = db.Column(db.Integer, db.ForeignKey("film.id"), nullable=False, index=True)
>>>>>>> feature/watchlist
```

Both sides had changed the same line for different reasons: `main` migrated
the type from integer to UUID, and this branch added an index.

**How I resolved it:** Took the UUID type from `main` and kept the index from
this branch:

```python
film_id = db.Column(db.String(36), db.ForeignKey("film.id"), nullable=False, index=True)
```

Accepting `main`'s side wholesale — the reflex when the incoming change is the
"real" refactor — would have silently dropped the index, and nothing in the
test suite would have caught it, because an index affects performance rather
than behaviour.

The rebase only resolves the conflicting line. It cannot see the integer
assumptions elsewhere in the branch that never conflicted because `main` has
no watchlist code to conflict with. I searched for those separately and found
three:

- `add_to_watchlist`'s docstring documented `film_id (int)` with a
  "pre-refactor" note
- the `POST /watchlist/<user_id>/add` body example read `{ "film_id": <int> }`
- the nonexistent-film test used `999999` as its sentinel

All three now use UUIDs. That cleanup is its own commit
(`fix: update watchlist film_id references to UUID after main branch
refactor`) rather than being folded into the conflict resolution, so the
history shows it as a deliberate step.

Deliberately left alone: `Film.year` and `CollectionEntry.rating` are also
integers and also matched my search. They have nothing to do with the ID
migration.

**How I verified no conflict remains:** `grep` for conflict markers in
`models.py` returns nothing; `git log --merges origin/main..HEAD` is empty, so
the branch is rebased rather than merged; `git status` is clean; and the full
test suite passes at 11 tests against the UUID schema.

---

## Commit history

Rewritten with `git rebase -i` into conventional format. The inherited commit
`added watchlist model and endpoint fixed a bug more changes` was reworded —
it was not conventional and described several changes at once. Each commit
below is one logical change, and there are no merge commits.

```
9570c3d feat: add remove_from_watchlist with matching DELETE endpoint
2855b6d feat: default watchlist entries to private and allow explicit visibility
f0c28ae fix: update watchlist film_id references to UUID after main branch refactor
7ad1d8c fix: sort watchlist by date added rather than alphabetically
f7ff3fb test: add watchlist tests for nonexistent film and duplicate entries
15757d4 fix: add deduplication check to prevent duplicate watchlist entries
9c437cb fix: rename save_to_watchlist to add_to_watchlist per naming convention
9c04af7 chore: add .gitignore for venv, caches, and local database
8793592 fix: update film retrieval method to use db.session.get in collection and watchlist services
5475943 feat: add watchlist model, service, and endpoint
```

---

## PR Description

### What this feature does

Adds a watchlist to CineLog: films a user intends to watch, kept separately
from their collection of films already watched. It provides three endpoints:

- `GET /watchlist/<user_id>` — returns the user's watchlist, newest first
- `POST /watchlist/<user_id>/add` — adds a film, optionally setting visibility
- `DELETE /watchlist/<user_id>/remove` — removes a film

The service layer mirrors `collection_service.py`: same `verb_to_noun` naming,
same exception types for the not-found and already-present cases, and the same
mapping of those exceptions to 404 and 409 in the route layer.

### Design decisions made

**Default visibility — watchlists are private by default.** Changed
`WatchlistEntry.public` from `default=True` to `default=False`, and added an
explicit `public` parameter so callers can opt in. The reasoning is that a
default is a choice made for every user who never opens settings, and the two
possible mistakes are not equally costly: a wrongly-private list is fixed with
one toggle, while a wrongly-public list has already disclosed something that
cannot be un-disclosed. The cost is real — a discovery feature built on public
watchlists is worth little if few are public. Full argument under Comment 4.

**Sort order — newest first, not alphabetical.** `get_watchlist()` orders by
`date_added` descending, matching `get_collection()`. A watchlist is a queue
you open to decide what to watch, not a catalogue you search by title, and two
list views in the same app sorting by different keys is a difference users
have to learn for no benefit. This does bury old entries on very long
watchlists; the right fix for that is explicit sort controls, filed as
follow-up. Full argument under Comment 5.

### How to test this manually

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python seed.py          # creates sample users and films
python app.py           # serves on http://127.0.0.1:5000
```

There is no frontend — `/` returns 404, which is expected. Use the REST
endpoints.

`seed.py` prints the demo user's id on the line
`Seeded 5 films and user 'demo' (user_id: ...)`. Film ids are UUIDs generated
at seed time and are not printed, so list them first:

```bash
curl http://127.0.0.1:5000/films/
```

Then, substituting a real `user_id` and two real `film_id` values:

```bash
# 1. Add a film. Expect 201 and "public": false in the response body.
curl -X POST http://127.0.0.1:5000/watchlist/<user_id>/add \
  -H "Content-Type: application/json" \
  -d '{"film_id": "<film_id>"}'

# 2. Add the same film again. Expect 409 and an "already on this user's
#    watchlist" error — not a second entry.
curl -X POST http://127.0.0.1:5000/watchlist/<user_id>/add \
  -H "Content-Type: application/json" \
  -d '{"film_id": "<film_id>"}'

# 3. Add a film that doesn't exist. Expect 404, not 500.
curl -X POST http://127.0.0.1:5000/watchlist/<user_id>/add \
  -H "Content-Type: application/json" \
  -d '{"film_id": "00000000-0000-0000-0000-000000000000"}'

# 4. Add a second real film with explicit public visibility. Expect 201
#    and "public": true.
curl -X POST http://127.0.0.1:5000/watchlist/<user_id>/add \
  -H "Content-Type: application/json" \
  -d '{"film_id": "<other_film_id>", "public": true}'

# 5. View the watchlist. Expect the film from step 4 first, since it was
#    added most recently — confirm it is not sorted by title.
curl http://127.0.0.1:5000/watchlist/<user_id>

# 6. Remove a film. Expect 200, then 404 when removing it a second time.
curl -X DELETE http://127.0.0.1:5000/watchlist/<user_id>/remove \
  -H "Content-Type: application/json" \
  -d '{"film_id": "<film_id>"}'
```

Automated coverage:

```bash
pytest tests/ -v
```

11 tests, covering the nonexistent-film case, deduplication, the visibility
default and override, sort order, and removal.
