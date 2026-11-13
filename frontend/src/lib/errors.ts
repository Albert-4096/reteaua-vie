// API errors in plain Romanian (T15, T16): the code picks the sentence, never the raw server message.
import type { TFunction } from "i18next";
import { ApiError } from "../api/client";

const KNOWN = ["ALREADY_PUBLISHED", "UNCONFIRMED", "NOT_FOUND", "NOT_ANALYZED", "INVALID_INPUT", "NETWORK"];

export function errorText(e: unknown, t: TFunction): string {
  const code = e instanceof ApiError ? e.code : "NETWORK";
  if (KNOWN.includes(code)) return t(`errors.${code}`);
  return t("errors.other", { code });
}
