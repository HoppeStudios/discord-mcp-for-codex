# Collaboration

This is a public MIT licensed fork. Preserve the upstream copyright and history.
Use review branches and PRs for changes. Do not push the default branch or merge
without explicit authorization. Keep secrets, receipts, machine paths, browser
profiles and user messages out of the repository.

Run `npm test` and `npm run smoke:test`. They must remain local and require no
token. Installing or testing is not authorization for a real Discord message.
Use only bot authentication. Keep personal account messaging in the existing
browser skill when the user requests that sender. Preserve stable request IDs,
unknown delivery stops, recipient verification and mention suppression.

Review pinned runtime provenance before deployment. No automatic updater or
Windows autostart is needed. Reuse the existing MCP registration during updates,
preserve its settings and defer replacement while its process is active. Verify
the replacement and remove superseded installations only after checking process
and registration dependencies. Do not create rollback copies.
