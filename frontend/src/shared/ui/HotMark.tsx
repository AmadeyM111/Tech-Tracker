// «Горит» (spec 008 FR-8): one mark for the summary list and the board card. The rule comes from the
// server (`hot`); the text is always shown, so the state is not carried by colour alone.
import { t } from "../i18n";
import "./hot-mark.css";

export function HotMark({ hot }: { hot: boolean }) {
  return hot ? <span className="ui-hot-mark" data-role="hot-mark">{t("summary.hot")}</span> : null;
}
