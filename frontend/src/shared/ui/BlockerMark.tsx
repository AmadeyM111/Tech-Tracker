// «Блокер» (spec 033): separate from «Горит» (spec 008). The rule comes from the server (`blocked`).
import { t } from "../i18n";
import "./blocker-mark.css";

export function BlockerMark({ blocked, block = false }: { blocked: boolean; block?: boolean }) {
  if (!blocked) return null;
  return (
    <span
      className={block ? "ui-blocker-mark ui-blocker-mark--block" : "ui-blocker-mark"}
      data-role="blocker-mark"
    >
      {t("summary.blocker")}
    </span>
  );
}
