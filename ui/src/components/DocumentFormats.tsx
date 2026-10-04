import { api } from "../api";
import { useLoad } from "../hooks";
import { t, useLocale } from "../i18n";

/** File-picker and folder hints use the same registry as service intake. */
export function DocumentFormats() {
  useLocale();
  const formats = useLoad("document-formats", api.documentFormats);
  if (formats.error) return <p className="notice small" role="status">{t("Supported formats could not be loaded.")}</p>;
  if (!formats.data) return <p className="muted small">{t("Loading supported formats…")}</p>;
  return <p className="muted small">{t("Supported formats")}: {formats.data.formats.map((f) => `${t(f.label)} (${f.suffix})`).join(" · ")}</p>;
}
