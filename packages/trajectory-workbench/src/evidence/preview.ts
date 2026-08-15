export interface ArtifactPreview {
  kind: 'json' | 'markdown' | 'text';
  content: string;
  truncated: boolean;
}

const PREVIEW_KINDS = new Map<string, ArtifactPreview['kind']>([
  ['application/json', 'json'],
  ['text/markdown', 'markdown'],
  ['text/plain', 'text'],
]);

function previewKind(response: Response): ArtifactPreview['kind'] {
  const contentType = response.headers.get('Content-Type')?.split(';', 1)[0]?.trim().toLowerCase() ?? '';
  const kind = PREVIEW_KINDS.get(contentType);
  if (!kind) throw new Error('Artifact response type is not safe to preview.');
  return kind;
}

function declaredTotal(response: Response): number | null {
  const contentRange = response.headers.get('Content-Range');
  const totalMatch = contentRange?.match(/\/(\d+)$/);
  if (totalMatch) return Number(totalMatch[1]);
  const contentLength = response.headers.get('Content-Length');
  if (!contentLength || !/^\d+$/.test(contentLength)) return null;
  return Number(contentLength);
}

async function readBounded(response: Response, maxBytes: number): Promise<{ bytes: Uint8Array; truncated: boolean }> {
  if (!response.body) {
    const value = new Uint8Array(await response.arrayBuffer());
    return { bytes: value.slice(0, maxBytes), truncated: value.byteLength > maxBytes };
  }

  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let retained = 0;
  let truncated = false;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const remaining = maxBytes - retained;
      if (remaining <= 0) {
        truncated = true;
        await reader.cancel();
        break;
      }
      const chunk = value.byteLength > remaining ? value.slice(0, remaining) : value;
      chunks.push(chunk);
      retained += chunk.byteLength;
      if (chunk.byteLength < value.byteLength) {
        truncated = true;
        await reader.cancel();
        break;
      }
    }
  } finally {
    reader.releaseLock();
  }

  const bytes = new Uint8Array(retained);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return { bytes, truncated };
}

/** Load display-only bytes through an already-authorized artifact gateway URL. */
export async function loadSafePreview(
  url: string,
  fetcher: typeof fetch,
  maxBytes = 131_072,
): Promise<ArtifactPreview> {
  if (!Number.isSafeInteger(maxBytes) || maxBytes <= 0) throw new Error('Artifact preview byte limit must be a positive integer.');
  const response = await fetcher(url, { headers: new Headers({ Range: `bytes=0-${maxBytes - 1}` }) });
  if (!response.ok) throw new Error(`Artifact preview request failed with status ${response.status}.`);
  const kind = previewKind(response);
  const bounded = await readBounded(response, maxBytes);
  const total = declaredTotal(response);
  return {
    kind,
    content: new TextDecoder().decode(bounded.bytes),
    truncated: bounded.truncated || (total !== null && total > bounded.bytes.byteLength),
  };
}
