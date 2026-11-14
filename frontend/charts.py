"""Plotly figures. Each function takes a ready frame from data.py and returns a figure.

No data access happens here, so charts can be tested with any frame.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from frontend import config



def _base_layout(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=8, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=config.FONT, size=12, color=config.INK_SECONDARY),
        hoverlabel=dict(font=dict(family=config.FONT), bgcolor="#0b1a33", bordercolor=config.AXIS),
    )
    axis = dict(gridcolor=config.GRID, linecolor=config.AXIS, zeroline=False,
                tickfont=dict(color=config.INK_MUTED))
    fig.update_xaxes(**axis)
    fig.update_yaxes(**axis)
    return fig


def _fmt(v: float) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "–"
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    if abs(v) >= 10:
        return f"{v:.0f}"
    return f"{v:.2g}"


def time_series(df: pd.DataFrame, unit: str, visible: list[str]) -> go.Figure:
    """Monthly totals per sensor, with the harmonized band and the sensor timeline marked."""
    fig = go.Figure()
    x = df["month"]

    if "Harmonized" in visible:
        fig.add_trace(go.Scatter(
            x=pd.concat([x, x[::-1]]), y=pd.concat([df["hi"], df["lo"][::-1]]),
            fill="toself", fillcolor=config.BAND_FILL, line=dict(width=0),
            name="Harmonized uncertainty", hoverinfo="skip", showlegend=True,
        ))

    # Raw series first so the harmonized line is drawn on top of them.
    for name in ["MODIS (raw)", "VIIRS (raw)", "Harmonized"]:
        if name not in visible:
            continue
        fig.add_trace(go.Scatter(
            x=x, y=df[name], name=name, mode="lines",
            line=dict(color=config.SERIES_COLORS[name], width=2.5 if name == "Harmonized" else 2),
            hovertemplate=f"{name}: %{{y:,.1f}} {unit}<extra></extra>",
        ))

    x0, x1 = x.min(), x.max()
    o0, o1 = max(config.VIIRS_START, x0), min(config.TRANSITION, x1)
    if o0 < o1:
        fig.add_vrect(x0=o0, x1=o1, fillcolor=config.GRID, opacity=0.45, line_width=0, layer="below")
        fig.add_annotation(x=o0 + (o1 - o0) / 2, y=1, yref="paper", yanchor="bottom",
                           text="MODIS + VIIRS overlap (calibration)", showarrow=False,
                           font=dict(size=11, color=config.INK_SECONDARY))
    if x0 < config.TRANSITION <= x1:
        fig.add_vline(x=config.TRANSITION, line=dict(color=config.INK_PRIMARY, width=1.5, dash="dot"))

    _base_layout(fig, height=360)
    fig.update_layout(
        hovermode="x unified",
        legend=dict(orientation="h", traceorder="normal", yanchor="bottom", y=1.08, x=0, font=dict(color=config.INK_SECONDARY)),
        margin=dict(t=56),
    )
    fig.update_yaxes(title=dict(text=unit, font=dict(color=config.INK_MUTED)), rangemode="tozero")
    fig.update_xaxes(showgrid=False, showspikes=True, spikemode="across", spikethickness=1,
                     spikecolor=config.AXIS, spikedash="solid")
    return fig
