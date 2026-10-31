// 263 (plan E, F1; the owner's decision of 2026-10-31: a confirmation card everywhere): the tests' way to carry out an
// action that asks for confirmation - its button opens the card, whose last button is the action itself.
import { screen, waitFor } from "@testing-library/react";

/** The action button of the open confirmation card. */
export function confirmAction(): HTMLButtonElement {
  const card = document.querySelector<HTMLElement>(".confirm-card");
  if (!card) throw new Error("no confirmation card is open");
  const buttons = card.querySelectorAll<HTMLButtonElement>("button");
  return buttons[buttons.length - 1];
}

/** The same, once the card has opened. */
export async function findConfirmAction(): Promise<HTMLButtonElement> {
  await waitFor(() => expect(document.querySelector(".confirm-card")).not.toBeNull());
  return confirmAction();
}

/** The open card's question. */
export const confirmQuestion = () => screen.getByText((_, el) => el?.classList.contains("confirm-question") ?? false);
