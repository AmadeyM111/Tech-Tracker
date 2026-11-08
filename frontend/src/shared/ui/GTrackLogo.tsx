// Логотип GTrack: планета на орбите, спутник и искра (интеллект). Декоративный inline SVG,
// без внешних запросов. Геометрия считается здесь, цвета берутся из ui.css (.ui-logo-*, токены темы).
// Пути передаются выражениями, а не строковыми атрибутами JSX (i18n-скан tests/shared/i18n.test.ts).

const CX = 32;
const CY = 32;
const ORBIT_RX = 28;
const ORBIT_RY = 10;
const ORBIT_TILT = (-18 * Math.PI) / 180;
const ORBIT_STEPS = 72;

function round(n: number): number {
  return Math.round(n * 100) / 100;
}

function circlePath(cx: number, cy: number, r: number): string {
  return `M${round(cx - r)} ${round(cy)}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0z`;
}

// Точка на эллипсе орбиты при параметре t (радианы), повёрнутом на ORBIT_TILT.
function orbitPoint(t: number): [number, number] {
  const x = ORBIT_RX * Math.cos(t);
  const y = ORBIT_RY * Math.sin(t);
  const cos = Math.cos(ORBIT_TILT);
  const sin = Math.sin(ORBIT_TILT);
  return [round(CX + x * cos - y * sin), round(CY + x * sin + y * cos)];
}

const ORBIT = `${Array.from({ length: ORBIT_STEPS }, (_, i) => {
  const [x, y] = orbitPoint((i / ORBIT_STEPS) * 2 * Math.PI);
  return `${i === 0 ? "M" : "L"}${x} ${y}`;
}).join("")}z`;

const PLANET = circlePath(CX, CY, 12);
const SATELLITE = (() => {
  const [x, y] = orbitPoint(-Math.PI / 3);
  return circlePath(x, y, 3.2);
})();
// Четырёхконечная искра над орбитой (путь строится функцией: строковая константа в d={} попала бы в i18n-скан).
function sparkPath(cx: number, cy: number, r: number): string {
  const k = r * 0.27;
  const p = (x: number, y: number) => `${round(x)} ${round(y)}`;
  return `M${p(cx, cy - r)}L${p(cx + k, cy - k)}L${p(cx + r, cy)}L${p(cx + k, cy + k)}L${p(cx, cy + r)}L${p(cx - k, cy + k)}L${p(cx - r, cy)}L${p(cx - k, cy - k)}z`;
}
const SPARK = sparkPath(50, 12, 6);
const STARS = [circlePath(8, 14, 1.3), circlePath(14, 54, 1.3), circlePath(56, 50, 1.3)].join("");

export function GTrackLogo() {
  return (
    <svg className="ui-logo" viewBox="0 0 64 64" aria-hidden="true" focusable={false}>
      <path className="ui-logo-orbit" d={ORBIT} />
      <path className="ui-logo-planet" d={PLANET} />
      <path className="ui-logo-satellite" d={SATELLITE} />
      <path className="ui-logo-spark" d={SPARK} />
      <path className="ui-logo-star" d={STARS} />
    </svg>
  );
}
