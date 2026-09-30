export type ClientLogLevel = "debug" | "info" | "warn" | "error";

export type ClientLogContext = Record<string, unknown>;

export interface ClientLogEntry {
  event: string;
  message?: string;
  context?: ClientLogContext;
  error?: unknown;
  correlationId?: string;
  requestId?: string;
}

export interface ClientLogger {
  debug: (entry: ClientLogEntry) => void;
  info: (entry: ClientLogEntry) => void;
  warn: (entry: ClientLogEntry) => void;
  error: (entry: ClientLogEntry) => void;
}

const isProduction = import.meta.env.PROD;
let productionOverride: boolean | null = null;

const writeToConsole = (level: ClientLogLevel, payload: ClientLogContext): void => {
  switch (level) {
    case "debug":
      console.debug(payload);
      break;
    case "info":
      console.info(payload);
      break;
    case "warn":
      console.warn(payload);
      break;
    case "error":
      console.error(payload);
      break;
    default: {
      const _exhaustive: never = level;
      throw new Error(`Unknown log level: ${_exhaustive}`);
    }
  }
};

const serializeError = (value: unknown): ClientLogContext | undefined => {
  if (value == null) {
    return undefined;
  }
  if (value instanceof Error) {
    return {
      name: value.name,
      message: value.message,
      stack: value.stack,
    };
  }
  if (typeof value === "string") {
    return { message: value };
  }
  if (typeof value === "object") {
    return value as ClientLogContext;
  }
  return { value };
};

const shouldLog = (level: ClientLogLevel): boolean => {
  const effectiveProduction = productionOverride ?? isProduction;
  if (!effectiveProduction) {
    return true;
  }
  return level === "warn" || level === "error";
};

const emit = (level: ClientLogLevel, entry: ClientLogEntry): void => {
  if (!shouldLog(level)) {
    return;
  }

  const payload: ClientLogContext = {
    timestamp: new Date().toISOString(),
    level,
    event: entry.event,
  };

  if (entry.message) {
    payload.message = entry.message;
  }
  if (entry.context) {
    payload.context = entry.context;
  }

  const correlationId = entry.correlationId;
  if (correlationId) {
    payload.correlationId = correlationId;
  }

  const requestId = entry.requestId;
  if (requestId) {
    payload.requestId = requestId;
  }

  const serializedError = serializeError(entry.error);
  if (serializedError) {
    payload.error = serializedError;
  }

  writeToConsole(level, payload);
};

export const setClientLoggerProductionOverride = (
  value: boolean | null
): void => {
  productionOverride = value;
};

export const clientLogger: ClientLogger = {
  debug: (entry) => emit("debug", entry),
  info: (entry) => emit("info", entry),
  warn: (entry) => emit("warn", entry),
  error: (entry) => emit("error", entry),
};
