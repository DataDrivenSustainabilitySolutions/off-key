const base64Url = (value: unknown): string =>
  btoa(JSON.stringify(value)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");

/** A JWT-shaped string with an unsigned header; only the payload matters to the client. */
export const unsignedJwt = (payload: unknown): string =>
  [base64Url({ alg: "none", typ: "JWT" }), base64Url(payload), ""].join(".");
