import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RecordBetForm } from "@/components/bets/RecordBetForm";

const owners = [
  { user_id: "u_tom", name: "Tom" },
  { user_id: "u_mike", name: "Mike" },
];

describe("RecordBetForm", () => {
  it("disables save until the form is valid, then submits cents", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<RecordBetForm owners={owners} onSave={onSave} onCancel={vi.fn()} />);

    const save = screen.getByRole("button", { name: /save bet/i });
    expect(save).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Side A"), {
      target: { value: "u_tom" },
    });
    fireEvent.change(screen.getByLabelText("Side B"), {
      target: { value: "u_mike" },
    });
    fireEvent.change(screen.getByLabelText("Amount ($)"), {
      target: { value: "500" },
    });
    fireEvent.change(screen.getByLabelText("The bet"), {
      target: { value: "Tom finishes above Mike" },
    });
    expect(save).toBeEnabled();

    fireEvent.click(save);
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0]).toMatchObject({
      side_a_owner_id: "u_tom",
      side_b_owner_id: "u_mike",
      amount_cents: 50000,
      description: "Tom finishes above Mike",
    });
  });

  it("keeps save disabled when both sides are the same owner", () => {
    render(
      <RecordBetForm owners={owners} onSave={vi.fn()} onCancel={vi.fn()} />,
    );
    fireEvent.change(screen.getByLabelText("Side A"), {
      target: { value: "u_tom" },
    });
    fireEvent.change(screen.getByLabelText("Side B"), {
      target: { value: "u_tom" },
    });
    fireEvent.change(screen.getByLabelText("Amount ($)"), {
      target: { value: "500" },
    });
    fireEvent.change(screen.getByLabelText("The bet"), {
      target: { value: "x" },
    });
    expect(screen.getByRole("button", { name: /save bet/i })).toBeDisabled();
  });
});
