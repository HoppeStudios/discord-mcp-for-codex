# Personal Discord browser MCP

Use the discovered `discord_personal` tools for personal account messages by
default. This adapter operates the ordinary web UI through the existing dedicated
Firefox MCP profile. It is not an official personal account API. No account token,
cookie, login secret, private application store or account API may be read or used.
Bot tools are only for an explicitly chosen bot sender.

1. Call `personal_identity` or `find_conversations` to read the visible account.
   `find_conversations(query)` searches visible recent DM links. A missing link
   does not prove a conversation does not exist. Resolve ambiguity before sending.
2. Use `inspect_conversation` with the exact channel URL and observed account
   username as `expected_sender`. Confirm the recipient or channel and exact
   composer label against the user's request. An existing draft is preserved.
3. For an authorized send use `send_personal_message` with the inspected URL,
   composer label, expected sender, exact content and one stable request ID.
   The adapter checks the visible account again before every Enter. It uses the
   existing helper's split messages, exact draft readback, pending receipts,
   single submission and persistence check for the same message ID after reload.
   No global mouse, keyboard or clipboard input is used.
4. For a draft only, use `prepare_personal_message`. It prepares the first planned
   part without submitting. Do not claim all parts are drafted or sent.
5. Report delivery only for `persisted_after_reload` or `already_verified` and the
   recorded message IDs. This is not evidence that the recipient read it.
   `delivery_unknown`, a failed readback, an existing pending receipt or a stale
   lock requires history inspection before recovery. Use `verify_personal_delivery`
   with the original exact arguments to check an existing pending receipt without
   resending. It verifies the author and the same unique message ID after reload.
   It stops on ambiguous or missing history. Never change request IDs,
   accounts or transports to evade it. Receipts share the helper's local store.
6. A missing login requires the user to sign in manually to the same dedicated
   profile. The manual Firefox profile stays untouched. The adapter closes its
   owned Firefox after each operation and refuses a busy profile. It never kills
   another browser or switches to foreground input.

If this MCP is absent, use the original Firefox helper described in SKILL.md.
Keep the same request ID and inspect uncertain receipts before any fallback.
Changing the installed helper or pinned runtime invalidates the adapter manifest
until reviewed. Do not disable that check or install an unpinned updater.
