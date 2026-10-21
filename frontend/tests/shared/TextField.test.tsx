// R6-T01 (006, plan 4.4 / PD-17): TextField.reveal - кнопка показа пароля.
// AC-3, AC-6 (иконки), AC-9, AC-10 на уровне компонента; D-6 (имя постоянное), FR-7.
// user-event в проекте нет: Enter/Space имитируются как в браузере - keydown(Enter) / keyup(Space)
// и, если событие не отменено (preventDefault), click по кнопке.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TextField } from "../../src/shared/ui/TextField";

afterEach(cleanup);

const LABEL = "Показать пароль";
const SECRET = "Secret-Pass-123";

function Harness(props: {
  disabled?: boolean;
  withReveal?: boolean;
  type?: "text" | "password";
  onToggleSpy?: () => void;
  hint?: string;
}) {
  const { disabled, withReveal = true, type = "password", onToggleSpy, hint } = props;
  const [shown, setShown] = useState(false);
  const [value, setValue] = useState("");
  return (
    <form>
      <TextField
        label="Пароль"
        value={value}
        onChange={setValue}
        type={type}
        autoComplete="current-password"
        disabled={disabled}
        hint={hint}
        reveal={
          withReveal
            ? {
                label: LABEL,
                shown,
                onToggle: () => {
                  onToggleSpy?.();
                  setShown((s) => !s);
                },
              }
            : undefined
        }
      />
    </form>
  );
}

const field = () => screen.getByLabelText("Пароль") as HTMLInputElement;
const btn = () => screen.getByRole("button", { name: LABEL }) as HTMLButtonElement;

function pressKey(el: HTMLElement, key: "Enter" | " ") {
  const code = key === " " ? "Space" : "Enter";
  if (key === "Enter") {
    if (fireEvent.keyDown(el, { key, code })) fireEvent.click(el);
  } else {
    const ok = fireEvent.keyDown(el, { key, code });
    const ok2 = fireEvent.keyUp(el, { key, code });
    if (ok && ok2) fireEvent.click(el);
  }
}

describe("TextField reveal", () => {
  it("ac3_markup_button_after_input_in_row", () => {
    const { container } = render(<Harness />);
    const row = container.querySelector("div.ui-field > div.ui-input-row");
    expect(row).not.toBeNull();
    const kids = Array.from((row as Element).children);
    expect(kids.map((k) => k.tagName)).toEqual(["INPUT", "BUTTON"]);
    const b = btn();
    expect(b.getAttribute("type")).toBe("button");
    expect(b.classList.contains("ui-reveal")).toBe(true);
    expect(b.getAttribute("aria-pressed")).toBe("false");
    expect(b.getAttribute("aria-label")).toBe(LABEL);
    expect(field().type).toBe("password");
  });

  it("ac6_icon_is_first_child_svg_aria_hidden", () => {
    render(<Harness />);
    const first = btn().firstElementChild;
    expect(first?.tagName.toLowerCase()).toBe("svg");
    expect(first?.getAttribute("aria-hidden")).toBe("true");
  });

  it("ac3_mouse_click_toggles_type_and_keeps_value", () => {
    render(<Harness />);
    fireEvent.change(field(), { target: { value: SECRET } });
    fireEvent.click(btn());
    expect(field().type).toBe("text");
    expect(field().value).toBe(SECRET);
    expect(btn().getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(btn());
    expect(field().type).toBe("password");
    expect(field().value).toBe(SECRET);
    expect(btn().getAttribute("aria-pressed")).toBe("false");
  });

  it("ac3_enter_and_space_call_onToggle", () => {
    const spy = vi.fn();
    render(<Harness onToggleSpy={spy} />);
    fireEvent.change(field(), { target: { value: SECRET } });
    btn().focus();
    pressKey(btn(), "Enter");
    expect(spy).toHaveBeenCalledTimes(1);
    expect(field().type).toBe("text");
    pressKey(btn(), " ");
    expect(spy).toHaveBeenCalledTimes(2);
    expect(field().type).toBe("password");
    expect(field().value).toBe(SECRET);
  });

  it("ac3_focus_stays_on_button_and_name_is_constant", () => {
    render(<Harness />);
    btn().focus();
    fireEvent.click(btn());
    expect(document.activeElement).toBe(btn());
    expect(btn().getAttribute("aria-label")).toBe(LABEL);
    fireEvent.click(btn());
    expect(document.activeElement).toBe(btn());
    expect(screen.getByRole("button", { name: LABEL })).toBe(btn());
  });

  it("ac6_icons_differ_between_modes", () => {
    render(<Harness />);
    const hidden = btn().querySelector("svg")?.innerHTML ?? "";
    expect(hidden).not.toBe("");
    fireEvent.click(btn());
    const shown = btn().querySelector("svg")?.innerHTML ?? "";
    expect(shown).not.toBe("");
    expect(shown).not.toBe(hidden);
    fireEvent.click(btn());
    expect(btn().querySelector("svg")?.innerHTML).toBe(hidden);
  });

  it("ac9_disabled_field_disables_button", () => {
    const spy = vi.fn();
    render(<Harness disabled onToggleSpy={spy} />);
    expect(field().disabled).toBe(true);
    expect(btn().disabled).toBe(true);
    fireEvent.click(btn());
    expect(spy).not.toHaveBeenCalled();
  });

  it("ac9_enabled_field_enables_button", () => {
    render(<Harness />);
    expect(btn().disabled).toBe(false);
  });

  it("ac10_field_attributes_and_hint_do_not_depend_on_shown", () => {
    render(<Harness hint="Не менее 12 символов" />);
    const snap = () => {
      const f = field();
      const hintId = f.getAttribute("aria-describedby");
      return {
        autocomplete: f.getAttribute("autocomplete"),
        autocapitalize: f.getAttribute("autocapitalize"),
        spellcheck: f.getAttribute("spellcheck"),
        describedby: hintId,
        hintText: hintId ? document.getElementById(hintId)?.textContent : null,
        label: screen.getByText("Пароль").textContent,
      };
    };
    const before = snap();
    expect(before.autocomplete).toBe("current-password");
    expect(before.autocapitalize).toBe("off");
    expect(before.spellcheck).toBe("false");
    expect(before.hintText).toBe("Не менее 12 символов");
    fireEvent.click(btn());
    expect(field().type).toBe("text");
    expect(snap()).toEqual(before);
  });

  it("no_reveal_means_no_button_and_old_markup", () => {
    const { container } = render(<Harness withReveal={false} />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(container.querySelector(".ui-input-row")).toBeNull();
    expect(container.querySelector(".ui-reveal")).toBeNull();
    expect(field().type).toBe("password");
  });

  it("reveal_ignored_for_text_type", () => {
    const { container } = render(<Harness type="text" />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(container.querySelector(".ui-input-row")).toBeNull();
    expect(field().type).toBe("text");
  });
});
