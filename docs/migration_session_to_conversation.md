# Migration Guide: `session_id` → `conversation_id`

Historical table `conversation_history` (flat `session_id` string) is now normalized to `conversations` + `messages`.

## Compatibility

- **Alias preserved**: all `/api/v1/chat/*` still accept `session_id` (string). Internally it maps to `conversations.legacy_session_id`.
- Deprecation header: responses include `X-Deprecated-Alias: session_id` when legacy field is used (future v4 will require `conversation_id`).
- **Backfill**: migration `e7f8a9b0c1d2_add_conversations_messages.py` copies existing `conversation_history` → `Conversation(title=first 50 chars)` + `Message` rows, preserving `user_id` isolation and `timestamp` order.
- Dual-write during transition: `save_exchange` writes to both new and legacy tables (best-effort legacy write inside `ConversationService.save_exchange`).

## New domain

```
Conversation(id, user_id FK CASCADE, title, model, created_at, updated_at, deleted_at, total_tokens, total_cost, legacy_session_id)
Message(id, conversation_id FK CASCADE, role enum['user','model','system','tool'], content, tokens, cost_usd, created_at, legacy_session_id)
Indexes: (user_id, updated_at), (user_id, legacy_session_id), (conversation_id, created_at)
```

Endpoints:

- `GET /api/v1/conversations?limit=20&cursor=0` → `PaginatedConversations(items, next_cursor, has_more)` ordered `updated_at desc`, filters `deleted_at is null`, `user_id` isolation.
- `GET /api/v1/conversations/{id}/messages?limit=50&cursor=...` → paginated messages.
- `PATCH /api/v1/conversations/{id}` `{title:"..."}` → rename (owner only).
- `DELETE /api/v1/conversations/{id}?hard=false` → soft-delete (sets `deleted_at`); `?hard=true` hard-deletes.

## Migration steps for clients

1. Continue sending `session_id` as before — no immediate change.
2. Opt-in to new ids: after `POST /chat/` or `/conversations`, capture `conversation_id` from `ConversationOut.id` and use it for pagination.
3. Update pagination: replace client-side `session_id` history fetch with `GET /conversations` + `GET /conversations/{id}/messages` (cursor).
4. Stop relying on legacy `GET /chat/history` (removed; internal `get_history` now delegates to `ConversationService`).
5. Handle soft-delete: `DELETE` no longer purges immediately; filter `deleted_at`.

## Rollback

If downgrade needed, legacy `conversation_history` still contains data until hard-delete migration. Downgrade `alembic downgrade e7f8...` restores flat table reads (but new conversations created after upgrade will be lost from legacy view).

## Checklist

- [ ] Verify `GET /conversations` returns same messages as old `session_id` query (compare counts).
- [ ] Check `X-Deprecated-Alias` header disappears after switching to `conversation_id`.
- [ ] Load-test after migration: cursor pagination should not leak across `user_id`.
