import React from "react";
import { Mark } from "./Mark.jsx";

const BASE = {
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
  border: 0,
  borderRadius: "var(--radius-sm)",
  padding: "11px 16px",
  minHeight: 44,
  fontFamily: "var(--font-mono)",
  fontSize: "9.5px",
  letterSpacing: ".12em",
  textTransform: "uppercase",
  cursor: "pointer",
  textDecoration: "none",
  transition: "background var(--dur-hover) var(--ease), border-color var(--dur-hover) var(--ease)",
};

/**
 * The primary fill is STAMP — one of its five sanctioned places. Ghost is a
 * 1.5px --rule-strong outline that darkens to ink on hover, never a second
 * fill: two filled buttons side by side make neither of them primary.
 *
 * 44px minimum height is unconditional. The one control in the system allowed
 * below it is the info tooltip trigger, which lives inside a 34px rule.
 */
export function Button({
  children,
  variant = "primary",
  icon,
  iconAfter,
  disabled = false,
  href,
  onClick,
  style,
  ...rest
}) {
  const tone =
    variant === "ghost"
      ? { background: "none", color: "var(--ink)", border: "1.5px solid var(--rule-strong)" }
      : { background: "var(--stamp)", color: "var(--stamp-ink)" };
  const s = { ...BASE, ...tone, ...(disabled ? { opacity: 0.42, cursor: "not-allowed" } : null), ...style };
  const body = (
    <>
      {icon ? <Mark name={icon} size={13} /> : null}
      {children}
      {iconAfter ? <Mark name={iconAfter} size={13} /> : null}
    </>
  );
  if (href && !disabled) return <a href={href} style={s} {...rest}>{body}</a>;
  return <button type="button" disabled={disabled} onClick={onClick} style={s} {...rest}>{body}</button>;
}
