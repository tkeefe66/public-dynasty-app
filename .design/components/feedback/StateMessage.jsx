import React from "react";
import { Mark } from "../controls/Mark.jsx";
import { Button } from "../controls/Button.jsx";

/**
 * Empty, error and not-found. Each says what happened in plain prose and
 * offers the one action that resolves it — an empty state with no way out is
 * a dead end, and "No data available" tells a reader nothing.
 */
export function StateMessage({ tone = "empty", title, body, action, onAction, href, style }) {
  const mark = tone === "error" ? "alert" : tone === "done" ? "done" : "info";
  const color = tone === "error" ? "var(--neg)" : "var(--dim)";
  return (
    <div
      style={{
        background: "var(--surface)",
        borderRadius: "var(--radius)",
        boxShadow: "var(--shadow)",
        padding: "28px 26px",
        display: "grid",
        gap: 9,
        justifyItems: "start",
        ...style,
      }}
    >
      <span style={{ color }}><Mark name={mark} size={16} /></span>
      <h3 style={{ margin: 0, fontFamily: "var(--font-display)", fontWeight: 800, fontSize: "var(--text-section)", letterSpacing: "-.026em" }}>{title}</h3>
      {body ? <p style={{ margin: 0, fontSize: "var(--text-body)", lineHeight: 1.6, color: "var(--body)", maxWidth: "56ch", textWrap: "pretty" }}>{body}</p> : null}
      {action ? <Button variant="ghost" href={href} onClick={onAction} style={{ marginTop: 4 }}>{action}</Button> : null}
    </div>
  );
}
