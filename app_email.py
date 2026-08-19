"""
Email Intelligence dashboard.
Run: streamlit run app.py
"""

import sqlite3

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Email Intelligence",
    layout="wide"
)

conn = sqlite3.connect("emails.db")

df = pd.read_sql(
    "SELECT * FROM emails ORDER BY received_at DESC",
    conn
)

st.title("Your inbox, triaged")
st.write(f"{len(df)} emails processed")

if df.empty:
    st.info("No data yet. Run `python process.py` first.")
    st.stop()


# -----------------------------
# Metrics
# -----------------------------

needs_action = df[
    (df["priority"] == "high") |
    (df["requires_action"] == 1)
]

important = df[
    (df["priority"] == "medium") &
    (df["requires_action"] == 0)
]

low = df[
    df["priority"] == "low"
]

col1, col2, col3 = st.columns(3)

col1.metric(
    "Needs action",
    len(needs_action)
)

col2.metric(
    "Important",
    len(important)
)

col3.metric(
    "Low priority",
    len(low)
)


# -----------------------------
# Filters
# -----------------------------

category_filter = st.multiselect(
    "Filter by category",
    sorted(df["category"].unique())
)

view = (
    df
    if not category_filter
    else df[df["category"].isin(category_filter)]
)


# -----------------------------
# Email sections
# -----------------------------

def show_section(title, subset):

    st.subheader(title)

    if subset.empty:
        st.write("Nothing here.")
        return

    for _, row in subset.iterrows():

        with st.expander(
            f"{row['subject']} — {row['sender']}"
        ):

            st.write(
                f"**Summary:** {row['summary']}"
            )

            st.write(
                f"**Suggested action:** "
                f"{row['suggested_action']}"
            )

            if row["deadline_phrase"] != "none":

                st.write(
                    f"**Deadline:** "
                    f"{row['deadline_phrase']} "
                    f"(parsed: {row['deadline_date']})"
                )

            st.write(
                f"**Why {row['priority']} priority:** "
                f"{row['reasoning']}"
            )

            st.caption(
                f"Category: {row['category']} • "
                f"Received: {row['received_at']}"
            )

            # -----------------------------
            # Actions
            # -----------------------------

            col1, col2 = st.columns(2)

            with col1:

                st.link_button(
                    "🔗 Open email",
                    row["email_url"]
                )

            with col2:

                attended = st.checkbox(
                    "✓ Attended",
                    value=bool(row["attended"]),
                    key=f"attended_{row['gmail_id']}"
                )

                # Save checkbox state to SQLite
                if attended != bool(row["attended"]):

                    conn.execute(
                        """
                        UPDATE emails
                        SET attended = ?
                        WHERE gmail_id = ?
                        """,
                        (
                            int(attended),
                            row["gmail_id"]
                        )
                    )

                    conn.commit()

                    # Update dataframe too
                    row["attended"] = int(attended)


# -----------------------------
# Render sections
# -----------------------------

show_section(
    "🔴 Needs action",
    view[
        (view["priority"] == "high") |
        (view["requires_action"] == 1)
    ]
)

show_section(
    "🟡 Important",
    view[
        (view["priority"] == "medium") &
        (view["requires_action"] == 0)
    ]
)

show_section(
    "🟢 Low priority",
    view[
        view["priority"] == "low"
    ]
)

conn.close()