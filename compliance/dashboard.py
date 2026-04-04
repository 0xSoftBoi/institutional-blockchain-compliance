"""
Dash web dashboard for the compliance monitoring system.

Runs on http://localhost:8050 by default.
Uses sample data when no live monitoring connection is available.
"""

import os
import random
import secrets
from datetime import datetime, timedelta, timezone

import dash
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from dash import Input, Output, dash_table, dcc, html
from flask import Response, request

# ---------------------------------------------------------------------------
# HTTP Basic Auth
# ---------------------------------------------------------------------------

DASHBOARD_USER = os.environ.get("DASHBOARD_USER", "")
DASHBOARD_PASS = os.environ.get("DASHBOARD_PASSWORD", "")


def _check_auth(username: str, password: str) -> bool:
    if not DASHBOARD_USER or not DASHBOARD_PASS:
        return True  # dev mode — no credentials configured
    return secrets.compare_digest(username, DASHBOARD_USER) and secrets.compare_digest(password, DASHBOARD_PASS)


def _require_auth():
    auth = request.authorization
    if not auth or not _check_auth(auth.username, auth.password):
        return Response(
            "Authentication required", 401,
            {"WWW-Authenticate": 'Basic realm="Compliance Dashboard"'},
        )

# ---------------------------------------------------------------------------
# Sample / mock data
# ---------------------------------------------------------------------------

def _generate_mock_transactions(n: int = 50) -> list[dict]:
    """Generate realistic-looking mock transaction data for the dashboard."""
    tiers = ["low", "low", "low", "low", "medium", "medium", "high", "critical"]
    tier_scores = {
        "low": (10, 49),
        "medium": (50, 74),
        "high": (75, 89),
        "critical": (90, 100),
    }
    addresses = [
        "0xabc123...def456",
        "0x111aaa...222bbb",
        "0xdeadbe...efcafe",
        "0x7f367c...c41522",
        "0x3d9819...508d61",
        "0xfa3851...2d8fe1",
        "0x8b3f1a...c99d22",
        "0x0d2abb...fe7193",
    ]

    now = datetime.now(timezone.utc)
    rows = []
    for i in range(n):
        tier = random.choice(tiers)
        lo, hi = tier_scores[tier]
        score = random.randint(lo, hi)
        amount = random.choice([
            random.uniform(100, 9_999),
            random.uniform(10_000, 99_999),
            random.choice([10_000, 25_000, 50_000, 100_000]),
        ])
        ts = now - timedelta(minutes=i * random.randint(1, 15))
        rows.append({
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "address": random.choice(addresses),
            "amount_usd": f"${amount:,.2f}",
            "score": score,
            "tier": tier.upper(),
            "requires_sar": tier in ("critical", "high"),
            # raw amount for time-series grouping
            "_amount_raw": amount,
            "_ts": ts,
        })

    rows.sort(key=lambda r: r["_ts"], reverse=True)
    return rows


def _tier_color(tier: str) -> str:
    return {
        "CRITICAL": "#e74c3c",
        "HIGH": "#e67e22",
        "MEDIUM": "#f1c40f",
        "LOW": "#2ecc71",
    }.get(tier.upper(), "#95a5a6")


# ---------------------------------------------------------------------------
# Dashboard factory
# ---------------------------------------------------------------------------

def create_app() -> dash.Dash:
    """Build and return the Dash application (does not start the server)."""

    app = dash.Dash(
        __name__,
        external_stylesheets=[dbc.themes.DARKLY],
        title="Blockchain Compliance Monitor",
        suppress_callback_exceptions=True,
    )

    # Require HTTP Basic Auth on every request
    app.server.before_request(lambda: _require_auth() or None)

    app.layout = dbc.Container(
        fluid=True,
        style={"backgroundColor": "#111827", "minHeight": "100vh", "padding": "24px"},
        children=[
            # ── Header ──────────────────────────────────────────────────────
            dbc.Row(
                dbc.Col(
                    html.Div([
                        html.H2(
                            "Blockchain Compliance Monitor",
                            style={"color": "#f8fafc", "fontWeight": 700, "marginBottom": "4px"},
                        ),
                        html.P(
                            "Real-time AML/KYC screening and risk analysis",
                            style={"color": "#94a3b8", "marginBottom": 0},
                        ),
                    ]),
                    width=12,
                ),
                style={"marginBottom": "24px"},
            ),

            # ── KPI cards ───────────────────────────────────────────────────
            dbc.Row(id="kpi-cards", style={"marginBottom": "24px"}),

            # ── Charts row ──────────────────────────────────────────────────
            dbc.Row([
                dbc.Col(
                    dbc.Card([
                        dbc.CardHeader("Risk Distribution", style={"color": "#f8fafc"}),
                        dbc.CardBody(dcc.Graph(id="pie-chart", style={"height": "320px"})),
                    ], style={"backgroundColor": "#1e293b", "border": "1px solid #334155"}),
                    md=4,
                ),
                dbc.Col(
                    dbc.Card([
                        dbc.CardHeader("Transaction Volume (USD)", style={"color": "#f8fafc"}),
                        dbc.CardBody(dcc.Graph(id="line-chart", style={"height": "320px"})),
                    ], style={"backgroundColor": "#1e293b", "border": "1px solid #334155"}),
                    md=8,
                ),
            ], style={"marginBottom": "24px"}),

            # ── Transaction feed ────────────────────────────────────────────
            dbc.Row(
                dbc.Col(
                    dbc.Card([
                        dbc.CardHeader(
                            "Live Transaction Feed",
                            style={"color": "#f8fafc"},
                        ),
                        dbc.CardBody(
                            dash_table.DataTable(
                                id="tx-table",
                                columns=[
                                    {"name": "Timestamp", "id": "timestamp"},
                                    {"name": "Address", "id": "address"},
                                    {"name": "Amount (USD)", "id": "amount_usd"},
                                    {"name": "Risk Score", "id": "score"},
                                    {"name": "Tier", "id": "tier"},
                                ],
                                style_table={"overflowX": "auto"},
                                style_header={
                                    "backgroundColor": "#0f172a",
                                    "color": "#94a3b8",
                                    "fontWeight": "600",
                                    "border": "1px solid #334155",
                                },
                                style_data={
                                    "backgroundColor": "#1e293b",
                                    "color": "#e2e8f0",
                                    "border": "1px solid #334155",
                                },
                                style_data_conditional=[
                                    {"if": {"filter_query": '{tier} = "CRITICAL"'},
                                     "color": "#e74c3c", "fontWeight": "700"},
                                    {"if": {"filter_query": '{tier} = "HIGH"'},
                                     "color": "#e67e22", "fontWeight": "600"},
                                    {"if": {"filter_query": '{tier} = "MEDIUM"'},
                                     "color": "#f1c40f"},
                                ],
                                page_size=15,
                                sort_action="native",
                            )
                        ),
                    ], style={"backgroundColor": "#1e293b", "border": "1px solid #334155"}),
                    width=12,
                ),
            ),

            # ── Interval for live refresh ────────────────────────────────────
            dcc.Interval(id="interval", interval=10_000, n_intervals=0),

            # ── Hidden store ─────────────────────────────────────────────────
            dcc.Store(id="tx-store"),
        ],
    )

    # -----------------------------------------------------------------------
    # Callbacks
    # -----------------------------------------------------------------------

    @app.callback(
        Output("tx-store", "data"),
        Input("interval", "n_intervals"),
    )
    def refresh_data(_):
        return _generate_mock_transactions(50)

    @app.callback(
        Output("kpi-cards", "children"),
        Input("tx-store", "data"),
    )
    def update_kpi_cards(data):
        if not data:
            data = _generate_mock_transactions(50)

        total = len(data)
        flagged = sum(1 for r in data if r["tier"] not in ("LOW",))
        critical = sum(1 for r in data if r["tier"] == "CRITICAL")
        sar_req = sum(1 for r in data if r.get("requires_sar"))

        def card(title, value, color):
            return dbc.Col(
                dbc.Card([
                    dbc.CardBody([
                        html.P(title, style={"color": "#94a3b8", "marginBottom": "4px", "fontSize": "0.85rem"}),
                        html.H3(str(value), style={"color": color, "fontWeight": 700, "marginBottom": 0}),
                    ])
                ], style={"backgroundColor": "#1e293b", "border": f"1px solid {color}"}),
                md=3,
            )

        return [
            card("Total Transactions", total, "#38bdf8"),
            card("Flagged Transactions", flagged, "#f1c40f"),
            card("Critical Alerts", critical, "#e74c3c"),
            card("SAR Required", sar_req, "#e67e22"),
        ]

    @app.callback(
        Output("pie-chart", "figure"),
        Input("tx-store", "data"),
    )
    def update_pie(data):
        if not data:
            data = _generate_mock_transactions(50)

        counts: dict[str, int] = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for r in data:
            counts[r["tier"]] = counts.get(r["tier"], 0) + 1

        labels = list(counts.keys())
        values = list(counts.values())
        colors = [_tier_color(t) for t in labels]

        fig = go.Figure(go.Pie(
            labels=labels,
            values=values,
            marker=dict(colors=colors),
            hole=0.45,
            textinfo="label+percent",
            textfont_color="#f8fafc",
        ))
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font_color="#f8fafc",
            legend=dict(font=dict(color="#94a3b8")),
            margin=dict(t=10, b=10, l=10, r=10),
            showlegend=True,
        )
        return fig

    @app.callback(
        Output("line-chart", "figure"),
        Input("tx-store", "data"),
    )
    def update_line(data):
        if not data:
            data = _generate_mock_transactions(50)

        # Bucket by 30-minute windows
        buckets: dict[str, float] = {}
        for r in data:
            ts = r.get("_ts")
            if ts is None:
                continue
            bucket = ts.replace(minute=(ts.minute // 30) * 30, second=0, microsecond=0)
            key = bucket.strftime("%H:%M")
            buckets[key] = buckets.get(key, 0) + r.get("_amount_raw", 0)

        sorted_buckets = sorted(buckets.items())
        x_vals = [k for k, _ in sorted_buckets]
        y_vals = [v for _, v in sorted_buckets]

        fig = go.Figure(go.Scatter(
            x=x_vals,
            y=y_vals,
            mode="lines+markers",
            line=dict(color="#38bdf8", width=2),
            marker=dict(color="#38bdf8", size=5),
            fill="tozeroy",
            fillcolor="rgba(56, 189, 248, 0.1)",
        ))
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font_color="#f8fafc",
            xaxis=dict(
                gridcolor="#334155",
                tickfont=dict(color="#94a3b8"),
                title="Time (UTC)",
                title_font=dict(color="#94a3b8"),
            ),
            yaxis=dict(
                gridcolor="#334155",
                tickfont=dict(color="#94a3b8"),
                tickprefix="$",
                title="Volume (USD)",
                title_font=dict(color="#94a3b8"),
            ),
            margin=dict(t=10, b=40, l=60, r=10),
        )
        return fig

    @app.callback(
        Output("tx-table", "data"),
        Input("tx-store", "data"),
    )
    def update_table(data):
        if not data:
            data = _generate_mock_transactions(50)

        return [
            {k: v for k, v in r.items() if not k.startswith("_") and k != "requires_sar"}
            for r in data
        ]

    return app


def run_dashboard(host: str = "127.0.0.1", port: int = 8050, debug: bool = False):
    """Start the Dash server."""
    app = create_app()
    app.run(host=host, port=port, debug=debug)
