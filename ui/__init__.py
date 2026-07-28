"""UI package for the triage console.

Layout:

    theme.py         design tokens + stylesheet injection
    domain.py        data loading, SLA clock, queue filtering, override log
    demo_context.py  deterministic simulated requester/thread/history (see D1)
    state.py         session-state helpers (open tabs, following, filters)
    components.py    reusable markup pieces
    views/           one module per navigation destination

``app.py`` is only an entry point: it boots the theme and hands off to
``st.navigation``.
"""
