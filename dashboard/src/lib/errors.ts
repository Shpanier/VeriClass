/** An API call that failed: the HTTP status and the server's own explanation. */
export class ApiError extends Error {
  status: number;
  /** True when the server couldn't be reached at all. */
  network: boolean;
  constructor(message: string, status = 0, network = false) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.network = network;
  }
}

type T = (key: "errNetwork" | "errServer" | "errUnknown") => string;

/** One sentence a lecturer can act on. The server's own sentences (4xx: "A
 *  password needs at least 6 characters") are shown as they are; a lost
 *  connection or a server crash gets our own wording. */
export function describeError(err: unknown, t: T): string {
  if (err instanceof ApiError) {
    if (err.network) return t("errNetwork");
    if (err.status >= 500) return t("errServer");
    return err.message || t("errUnknown");
  }
  if (err instanceof Error && err.message) return err.message;
  return t("errUnknown");
}
