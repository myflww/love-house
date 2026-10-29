# Recording-source deduplication

`dedup.py` groups multiple captures of one dialogue without deleting either raw node or any archive receipt. It is not a semantic fact merger: the organizer separately merges facts with validated evidence.

Automatic grouping requires the same known window/session, exactly matching full user and assistant texts (only CRLF and outer whitespace normalized), cross manual/passive capture channels, and a unique match within 120 seconds. An explicit shared source-event identity can match delayed delivery. Different windows, partial replies, or ambiguous repeated turns are only possible-duplicate review groups. Repeated real turns from the same capture channel remain distinct. A passive source is preferred as canonical because it normally has the actual archive receipt.

Original node IDs, original user text, assistant reply and idempotent request hashes remain. Confirmed aliases carry `meta.duplicate_of`, `exclude_for_recall`, guards and a `source_ids` dependency. Canonical `recording_sources` lists the source captures, including node ID, role/session provenance, actual receipt and capture timestamp when available. These are multiple captures, not independent confirmations of a fact.

Public helpers:

- `annotate_turn_recording(brain,nid,origin=...,external_session_id=...,source_event_id=...,connection_id=...)` validates and registers a capture under the owning library transaction.
- `canonical_id(brain,node_or_id)` follows a valid source group, rejects edited/stale alias guards, and honors privacy tombstones.
- `is_duplicate(node,brain=None)` identifies only confirmed aliases. Pass `brain` so edited or removed canonical targets are handled safely.
- `canonical_turns(brain,session_id=None)` supplies one primary dialogue per source group; each source's internal session remains valid for history lookup.
- `reconcile_recordings(brain)` explicitly annotates existing legacy raw nodes. It does not persist on its own. A large, ambiguous import becomes a review group rather than selecting a random capture.
- `possible_groups(brain,limit=50)` is read-only and returns bounded human-readable records and `expected` content/state guards. Unknown candidates must not be hidden.
- `confirm_duplicate(brain,canonical,alias_ids,expected)` explicitly confirms a view/index merge. It retains all source bodies; edited or deleted inputs reject stale confirmation.
- `separate_recordings(brain,node_id,expected)` reverses an index merge and remembers the human separation so reconciliation does not immediately merge it back.
- `recording_version(node)` supplies the guard used by the two explicit review actions.

`record_turn` accepts optional origin and source-reference keyword fields. `ingest_event` supplies passive provenance before grouping and refreshes it after adding the raw receipt. Its response contains `node_ids` for the canonical index and `record_node_ids` for the original capture; **only a nonempty `duplicate_of` means this particular capture is an alias**. A newly preferred passive canonical may have `deduplicated:true` and `duplicate_of:null` and still needs ordinary organizer processing.

The host must use the validated alias filter for retrieval/visualization, retain the raw archive and receipts, and skip organizer billing for already-confirmed alias inputs. A browser must not hide a record merely because its text resembles another record. Metadata must not be used to count two source copies as two independent persona feedback rounds; `history` and persona evidence selection now resolve canonical turns.

Deleting or disabling the canonical record traverses the existing `source_ids` dependency and its aliases. A privacy tombstone cannot promote a source back into memory. If a primary index node was only evicted for capacity, an extant original capture may become a safe single fallback; this does not recreate deleted data.

The new tests use only temporary brains and offline functions. They do not inspect the user's active conversations, API credentials or real profile.
