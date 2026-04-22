import { env } from "node:process";

type MailpitMessageSummary = Record<string, unknown>;

const DEFAULT_MAILPIT_BASE_URL = env.MAILPIT_BASE_URL ?? "http://localhost:8025";
const DEFAULT_FRONTEND_BASE_URL =
  env.PLAYWRIGHT_BASE_URL ?? env.FRONTEND_BASE_URL ?? "http://localhost:5173";
const DEFAULT_TIMEOUT_MS = Number(env.MAILPIT_POLL_TIMEOUT_MS ?? "120000");
const DEFAULT_INTERVAL_MS = Number(env.MAILPIT_POLL_INTERVAL_MS ?? "2000");

const sleep = (ms: number) =>
  new Promise<void>((resolve) => {
    setTimeout(resolve, ms);
  });

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null;

const escapeForRegex = (value: string): string =>
  value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

const extractEmails = (value: string): string[] => {
  const matches = value.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi);
  return matches ? matches.map((match) => match.toLowerCase()) : [];
};

const normalizeAddresses = (value: unknown): string[] => {
  if (typeof value === "string") {
    return extractEmails(value);
  }

  if (Array.isArray(value)) {
    return value.flatMap(normalizeAddresses);
  }

  if (!isRecord(value)) {
    return [];
  }

  const addresses: string[] = [];
  for (const key of ["Address", "address", "Email", "email"]) {
    const candidate = value[key];
    if (typeof candidate === "string") {
      addresses.push(...extractEmails(candidate));
    }
  }

  const mailbox = value.Mailbox ?? value.mailbox;
  const domain = value.Domain ?? value.domain;
  if (typeof mailbox === "string" && typeof domain === "string") {
    addresses.push(`${mailbox}@${domain}`.toLowerCase());
  }

  return [...new Set(addresses)];
};

const extractMessageSummaries = (payload: unknown): MailpitMessageSummary[] => {
  if (Array.isArray(payload)) {
    return payload.filter(isRecord);
  }

  if (!isRecord(payload)) {
    return [];
  }

  for (const key of ["messages", "Messages"]) {
    const candidate = payload[key];
    if (Array.isArray(candidate)) {
      return candidate.filter(isRecord);
    }
  }

  return [];
};

const getMessageId = (summary: MailpitMessageSummary): string | null => {
  for (const key of ["ID", "Id", "id"]) {
    const candidate = summary[key];
    if (typeof candidate === "string" && candidate.length > 0) {
      return candidate;
    }
  }

  return null;
};

const getMessageTimestamp = (summary: MailpitMessageSummary): number => {
  for (const key of ["Created", "created", "Date", "date"]) {
    const candidate = summary[key];
    if (typeof candidate === "string") {
      const timestamp = Date.parse(candidate);
      if (!Number.isNaN(timestamp)) {
        return timestamp;
      }
    }
  }

  return 0;
};

const summaryIncludesRecipient = (
  summary: MailpitMessageSummary,
  email: string
): boolean => {
  const normalizedEmail = email.toLowerCase();
  const addressCollections = [
    summary.To,
    summary.to,
    summary.Recipients,
    summary.recipients,
  ];

  return addressCollections
    .flatMap(normalizeAddresses)
    .some((address) => address === normalizedEmail);
};

const collectStrings = (
  value: unknown,
  seen: WeakSet<object> = new WeakSet()
): string[] => {
  if (typeof value === "string") {
    return [value];
  }

  if (Array.isArray(value)) {
    if (seen.has(value)) {
      return [];
    }
    seen.add(value);
    return value.flatMap((item) => collectStrings(item, seen));
  }

  if (!isRecord(value)) {
    return [];
  }

  if (seen.has(value)) {
    return [];
  }
  seen.add(value);

  return Object.values(value).flatMap((item) => collectStrings(item, seen));
};

const extractVerificationLink = (
  payload: unknown,
  frontendBaseUrl: string
): string | null => {
  const normalizedBaseUrl = frontendBaseUrl.replace(/\/$/, "");
  const linkPattern = new RegExp(
    `${escapeForRegex(normalizedBaseUrl)}\\/verify\\?token=[^\\s"'<>]+`,
    "i"
  );

  for (const text of collectStrings(payload)) {
    const match = text.match(linkPattern);
    if (match) {
      return match[0];
    }
  }

  return null;
};

const fetchMailpitJson = async (
  path: string,
  mailpitBaseUrl: string
): Promise<unknown> => {
  const url = new URL(path, mailpitBaseUrl);
  const response = await fetch(url, {
    headers: {
      Accept: "application/json",
    },
  });

  if (!response.ok) {
    throw new Error(`Mailpit request failed: ${response.status} ${url.toString()}`);
  }

  return response.json();
};

export const waitForVerificationLink = async (
  email: string,
  options?: {
    mailpitBaseUrl?: string;
    frontendBaseUrl?: string;
    timeoutMs?: number;
    pollIntervalMs?: number;
  }
): Promise<string> => {
  const mailpitBaseUrl = options?.mailpitBaseUrl ?? DEFAULT_MAILPIT_BASE_URL;
  const frontendBaseUrl =
    options?.frontendBaseUrl ?? DEFAULT_FRONTEND_BASE_URL;
  const timeoutMs = options?.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const pollIntervalMs = options?.pollIntervalMs ?? DEFAULT_INTERVAL_MS;
  const deadline = Date.now() + timeoutMs;

  let lastError: unknown;
  while (Date.now() < deadline) {
    try {
      const summariesPayload = await fetchMailpitJson(
        "/api/v1/messages",
        mailpitBaseUrl
      );
      const summaries = extractMessageSummaries(summariesPayload)
        .filter((summary) => summaryIncludesRecipient(summary, email))
        .sort((left, right) => getMessageTimestamp(right) - getMessageTimestamp(left));

      const latestMessage = summaries[0];
      if (latestMessage) {
        const messageId = getMessageId(latestMessage);
        if (!messageId) {
          throw new Error("Mailpit message summary is missing an ID");
        }

        const detailPayload = await fetchMailpitJson(
          `/api/v1/message/${messageId}`,
          mailpitBaseUrl
        );
        const verificationLink = extractVerificationLink(
          detailPayload,
          frontendBaseUrl
        );

        if (verificationLink) {
          return verificationLink;
        }

        throw new Error(
          `Mailpit message ${messageId} did not contain a verification link`
        );
      }
    } catch (error) {
      lastError = error;
    }

    await sleep(pollIntervalMs);
  }

  const errorSuffix =
    lastError instanceof Error ? ` Last error: ${lastError.message}` : "";
  throw new Error(
    `Timed out waiting for verification email for ${email}.${errorSuffix}`
  );
};
