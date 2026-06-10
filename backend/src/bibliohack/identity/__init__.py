"""Identity context — users, authentication, sessions.

The Identity milestone (ARCHITECTURE.md §4, docs/identity-milestone-plan.md):
`User` aggregate with Argon2id password auth, Redis-backed server-side
sessions, email verification + password reset over the NAS SMTP mailer, and
optional Cloudflare Turnstile bot protection on register/login.
"""
