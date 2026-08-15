import { describe, expect, it, vi } from 'vitest';
import { loadSafePreview } from './preview';

describe('loadSafePreview', () => {
  it('requests and retains no more than the configured JSON byte range', async () => {
    const payload = '{"result":"abcdefghijklmnopqrstuvwxyz"}';
    const fetcher = vi.fn<typeof fetch>(async (_url, init) => {
      expect(new Headers(init?.headers).get('Range')).toBe('bytes=0-15');
      return new Response(payload, {
        headers: { 'Content-Type': 'application/json; charset=utf-8', 'Content-Length': String(payload.length) },
      });
    });

    const preview = await loadSafePreview('/api/runs/analysis-test/artifacts/evidence:one', fetcher, 16);

    expect(preview).toEqual({ kind: 'json', content: payload.slice(0, 16), truncated: true });
    expect(new TextEncoder().encode(preview.content)).toHaveLength(16);
  });

  it.each([
    ['text/markdown; charset=utf-8', 'markdown'],
    ['text/plain', 'text'],
  ] as const)('accepts the fixed safe %s media type', async (contentType, kind) => {
    const preview = await loadSafePreview('/artifact', async () => new Response('safe text', {
      headers: { 'Content-Type': contentType },
    }));

    expect(preview).toEqual({ kind, content: 'safe text', truncated: false });
  });

  it('rejects executable or unexpected response media types', async () => {
    await expect(loadSafePreview('/artifact', async () => new Response('<script />', {
      headers: { 'Content-Type': 'text/html' },
    }))).rejects.toThrow('not safe to preview');
  });

  it('rejects an unsuccessful artifact response without exposing its body', async () => {
    await expect(loadSafePreview('/artifact', async () => new Response('private diagnostic', {
      status: 403,
      headers: { 'Content-Type': 'text/plain' },
    }))).rejects.toThrow('Artifact preview request failed with status 403');
  });
});
