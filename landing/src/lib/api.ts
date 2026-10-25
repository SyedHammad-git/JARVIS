"use client";

export type TokenGetter = (options?: { skipCache?: boolean }) => Promise<string | null>;

export type ApiErrorCode =
  | "no_api_key"
  | "offline"
  | "authentication_required"
  | "api_key_storage_unavailable"
  | string;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly code: ApiErrorCode,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type ApiOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
};

function backendBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_BACKEND_URL;
  if (!configured) {
    throw new ApiError("The backend URL has not been configured.", "offline", 0);
  }
  const url = new URL(configured);
  if (process.env.NODE_ENV === "production" && url.protocol !== "https:") {
    throw new ApiError("The backend must use HTTPS in production.", "offline", 0);
  }
  return url.toString().replace(/\/$/, "");
}

function signIn(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event("jarvis:sign-in-required"));
  }
}

export async function apiFetch<T>(
  getToken: TokenGetter,
  path: string,
  options: ApiOptions = {},
  onUnauthenticated: () => void = signIn,
): Promise<T> {
  const baseUrl = backendBaseUrl();
  const request = async (refresh: boolean) => {
    let token: string | null;
    try {
      token = await getToken(refresh ? { skipCache: true } : undefined);
    } catch {
      throw new ApiError("Could not refresh your sign-in session. Check your connection and try again.", "offline", 0);
    }
    if (!token) {
      onUnauthenticated();
      throw new ApiError("Your session has expired. Sign in again.", "authentication_required", 401);
    }
    const headers = new Headers(options.headers);
    headers.set("Authorization", `Bearer ${token}`);
    if (options.body !== undefined) headers.set("Content-Type", "application/json");
    try {
      return await fetch(`${baseUrl}${path}`, {
        ...options,
        headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        cache: "no-store",
      });
    } catch {
      throw new ApiError("The backend could not be reached. Check your connection and try again.", "offline", 0);
    }
  };

  let response = await request(false);
  if (response.status === 401) response = await request(true);
  if (response.status === 401) {
    onUnauthenticated();
    throw new ApiError("Your session has expired. Sign in again.", "authentication_required", 401);
  }

  let payload: { error?: unknown; [key: string]: unknown };
  try {
    payload = await response.json();
  } catch {
    throw new ApiError("The backend returned an unreadable response. Please try again.", "invalid_response", response.status);
  }
  if (!response.ok) {
    const code = typeof payload?.error === "string" ? payload.error : "request_failed";
    if (code === "no_api_key") {
      throw new ApiError("Add an AI provider key in Settings to start chatting.", code, response.status);
    }
    if (code === "api_key_storage_unavailable") {
      throw new ApiError("Secure key storage is not configured on the backend.", code, response.status);
    }
    if (code === "pair_code_expired_or_invalid") {
      throw new ApiError("This pairing code has expired or is invalid. Generate a new one.", code, response.status);
    }
    throw new ApiError(
      code === "authentication_required"
        ? "Your session has expired. Sign in again."
        : "That request could not be completed. Please try again.",
      code,
      response.status,
    );
  }
  return payload as T;
}
