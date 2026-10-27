export type DownloadRelease = {
  url?: string;
  version?: string;
  sha256?: string;
  invalidUrl: boolean;
  invalidChecksum: boolean;
};

function releaseAssetUrl(value: string | undefined): string | undefined {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.hostname === "github.com" && /\/releases\/download\/[^/]+\/[^/]+$/.test(url.pathname)
      ? url.toString()
      : undefined;
  } catch {
    return undefined;
  }
}

function releaseVersion(value: string | undefined): string | undefined {
  return value && /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/.test(value) ? value : undefined;
}

function releaseChecksum(value: string | undefined): string | undefined {
  return value && /^[a-f\d]{64}$/i.test(value) ? value.toLowerCase() : undefined;
}

export function getDownloadRelease(url: string | undefined, version: string | undefined, sha256: string | undefined): DownloadRelease {
  return {
    url: releaseAssetUrl(url),
    version: releaseVersion(version),
    sha256: releaseChecksum(sha256),
    invalidUrl: Boolean(url && !releaseAssetUrl(url)),
    invalidChecksum: Boolean(sha256 && !releaseChecksum(sha256)),
  };
}