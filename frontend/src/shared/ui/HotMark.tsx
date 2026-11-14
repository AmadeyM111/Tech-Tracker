// «Горит» (spec 008 FR-8): one mark for the summary list and the board card. The rule comes from the
// server (`hot`); the text is always shown, so the state is not carried by colour alone.
import { t } from "../i18n";
import "./hot-mark.css";

// `block`: the mark takes its own line (the board card, every width). Default is inline (the summary row).
export function HotMark({ hot, block = false }: { hot: boolean; block?: boolean }) {
  if (!hot) return null;
  return (
    <span className={block ? "ui-hot-mark ui-hot-mark--block" : "ui-hot-mark"} data-role="hot-mark">
      {t("summary.hot")}
    </span>
  );
}
