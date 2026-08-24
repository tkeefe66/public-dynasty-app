"use client";
import { ReceiptButton } from "./ReceiptButton";

/** Server-component-friendly wrapper: the trade page is a server component and
 *  can't pass function props to a client component, so it computes the receipt
 *  string + path server-side and this wrapper re-closes them into the `() =>
 *  string` shape `ReceiptButton` expects. */
export function TradeReceiptButton({ claim, path }: { claim: string; path: string }) {
  return <ReceiptButton claim={() => claim} path={() => path} />;
}
