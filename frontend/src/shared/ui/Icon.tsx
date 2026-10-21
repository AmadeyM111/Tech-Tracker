// T100: inline SVG icons (no dependencies, no external requests). Decorative only: the accessible
// name always comes from the text next to the icon. Colour, stroke width and caps come from ui.css
// (`.ui-icon`, `currentColor`). Shapes are path data only (24x24 grid) so no Latin attribute literals
// sit in the JSX (the i18n scan of tests/shared/i18n.test.ts).
export type IconName = "projects" | "tasks" | "users" | "audit" | "password" | "logout" | "plus" | "eye" | "eye-off";

const PATHS: Record<IconName, string[]> = {
  // Folder.
  projects: ["M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"],
  // Checked box.
  tasks: ["M7 4h10a3 3 0 0 1 3 3v10a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3V7a3 3 0 0 1 3-3z", "M8.5 12.5l2.5 2.5 4.5-5"],
  // Two people.
  users: [
    "M5.5 8a3.5 3.5 0 1 0 7 0a3.5 3.5 0 1 0-7 0",
    "M2.5 20a6.5 6.5 0 0 1 13 0",
    "M16 4.8a3.5 3.5 0 0 1 0 6.4",
    "M18 14.2a6.5 6.5 0 0 1 3.5 5.8",
  ],
  // Document with lines.
  audit: ["M6 3h8l4 4v14H6z", "M14 3v4h4", "M9 12h6M9 16h6"],
  // Key.
  password: ["M4 15a4 4 0 1 0 8 0a4 4 0 1 0-8 0", "M11 12l9-9", "M16 7l3 3"],
  // Arrow leaving a door.
  logout: ["M10 4H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h5", "M16 8l4 4-4 4", "M20 12H9"],
  // Plus.
  plus: ["M12 5v14", "M5 12h14"],
  // Eye.
  eye: ["M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z", "M9 12a3 3 0 1 0 6 0a3 3 0 1 0-6 0"],
  // Eye crossed out by a diagonal.
  "eye-off": [
    "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z",
    "M9 12a3 3 0 1 0 6 0a3 3 0 1 0-6 0",
    "M3 3l18 18",
  ],
};

export function Icon({ name }: { name: IconName }) {
  return (
    <svg className="ui-icon" viewBox="0 0 24 24" aria-hidden="true" focusable={false}>
      {PATHS[name].map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}
