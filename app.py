"""Stage 4 — Jordan's Ticket Triage Assistant (Streamlit UI).

The payoff of the whole pipeline: instead of opening an unsorted queue and
running an AI assistant ticket-by-ticket, Jordan opens an already-sorted console.

This file is only the entry point — it boots the theme, mounts the brand mark,
and hands off to ``st.navigation``. The views live in ``ui/views/`` and the data
layer in ``ui/domain.py``.

Navigation mirrors a support agent's day rather than the codebase's structure:

    Home                     what needs me right now
    Your work                Tickets · Safety-net escalations
    Shared work              Following
    Completed work           Last 30 days
    Insights                 Reporting · Settings

Run:  ``streamlit run app.py``
"""

from __future__ import annotations

import streamlit as st

from ui import domain, theme
from ui.views import completed, following, home, reporting, settings, tickets


def _no_data_screen() -> None:
    """Shown when the batch job hasn't run — keeps the shell, explains the fix."""
    st.html(
        '<div class="tc-appbar"><div>'
        '<p class="tc-appbar__title">No classified tickets found</p>'
        '<p class="tc-appbar__sub">The console needs a classified batch to render a queue.</p>'
        "</div></div>"
    )
    st.error(
        "Run `python src/data_prep.py` and then `python -m src.batch_classify` "
        "to generate `data/processed/classified_tickets.json`."
    )
    st.caption(
        "A committed demo sample normally covers this. If you're seeing this "
        "message, both the full batch and the sample are missing."
    )


def main() -> None:
    st.set_page_config(
        page_title="Triage Console",
        page_icon="🎫",
        layout="wide",
        # "auto", not "expanded": expanded forces the 268px rail open on a phone,
        # where it renders as an overlay covering the queue the agent came to
        # read. "auto" keeps it open on desktop and collapsed on narrow screens.
        # Found by /qa.
        initial_sidebar_state="auto",
    )
    theme.inject_css()
    st.logo(
        theme.logo_data_uri(theme.LOGO_PATH),
        icon_image=theme.logo_data_uri(theme.LOGO_MARK_PATH),
        size="large",
    )

    if not domain.load_tickets():
        _no_data_screen()
        return

    tickets_page = st.Page(
        tickets.render, title="Tickets",
        icon=":material/confirmation_number:", url_path="tickets",
    )
    # Home reaches for this when the agent opens a ticket from the attention list.
    st.session_state["_page_tickets"] = tickets_page

    nav = st.navigation(
        {
            "": [
                st.Page(home.render, title="Home", icon=":material/home:",
                        url_path="home", default=True),
            ],
            "Your work": [
                tickets_page,
                st.Page(tickets.render_safety_net, title="Safety-net escalations",
                        icon=":material/shield:", url_path="safety-net"),
            ],
            "Shared work": [
                st.Page(following.render, title="Following",
                        icon=":material/visibility:", url_path="following"),
            ],
            "Completed work": [
                st.Page(completed.render, title="Last 30 days",
                        icon=":material/task_alt:", url_path="completed"),
            ],
            "Insights": [
                st.Page(reporting.render, title="Reporting",
                        icon=":material/bar_chart:", url_path="reporting"),
                st.Page(settings.render, title="Settings",
                        icon=":material/settings:", url_path="settings"),
            ],
        }
    )
    nav.run()


if __name__ == "__main__":
    main()
