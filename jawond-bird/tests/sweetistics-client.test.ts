import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SweetisticsClient } from '../src/lib/sweetistics-client.js';

describe('SweetisticsClient', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.resetAllMocks();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it('posts tweet with bearer token and reply id', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ success: true, tweetId: '123' }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const client = new SweetisticsClient({ baseUrl: 'https://api.example.com', apiKey: 'sweet-test' });
    const result = await client.tweet('hello world', '456');

    expect(result.success).toBe(true);
    expect(result.tweetId).toBe('123');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('https://api.example.com/api/actions/tweet');
    expect((init as RequestInit).headers).toMatchObject({ authorization: 'Bearer sweet-test' });
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ text: 'hello world', replyToTweetId: '456' });
  });

  it('returns error when API responds with failure', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ success: false, error: 'Unauthorized' }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const client = new SweetisticsClient({ baseUrl: 'https://api.example.com', apiKey: 'sweet-test' });
    const result = await client.tweet('test');

    expect(result.success).toBe(false);
    expect(result.error).toContain('Unauthorized');
  });

  it('uploads media and passes mediaIds into tweet', async () => {
    const fetchMock = vi
      .fn()
      // upload
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ mediaId: 'mid-1' }),
      })
      // tweet
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ success: true, tweetId: '789' }),
      });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const client = new SweetisticsClient({ baseUrl: 'https://api.example.com', apiKey: 'sweet-test' });
    const uploadRes = await client.uploadMedia({ data: 'Zm9v', mimeType: 'image/png', alt: 'foo' });
    expect(uploadRes.success).toBe(true);
    expect(uploadRes.mediaId).toBe('mid-1');

    const tweetRes = await client.tweet('hi', undefined, ['mid-1']);
    expect(tweetRes.success).toBe(true);

    // First call: upload; second call: tweet with mediaIds
    const [, tweetInit] = fetchMock.mock.calls[1];
    expect(JSON.parse((tweetInit as RequestInit).body as string)).toMatchObject({ mediaIds: ['mid-1'] });
  });

  it('reads a tweet', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        id: '1',
        text: 'hi',
        author: { username: 'u', name: 'User' },
        metrics: { likeCount: 5 },
      }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const client = new SweetisticsClient({ baseUrl: 'https://api.example.com', apiKey: 'sweet-test' });
    const result = await client.read('1');

    expect(result.success).toBe(true);
    expect(result.tweet?.id).toBe('1');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('https://api.example.com/api/tweets/1');
    expect((init as RequestInit).headers).toMatchObject({ authorization: 'Bearer sweet-test' });
  });

  it('fetches replies', async () => {
    const conversationPayload = {
      tweetIds: ['1', '2'],
      tweets: {
        1: {
          id: '1',
          text: 'root',
          author: { username: 'root', name: 'Root' },
          conversationId: 'c1',
        },
        2: {
          id: '2',
          text: 'reply',
          author: { username: 'reply', name: 'Reply' },
          conversationId: 'c1',
          inReplyToStatusId: '1',
        },
      },
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        result: { data: conversationPayload },
      }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const client = new SweetisticsClient({ baseUrl: 'https://api.example.com', apiKey: 'sweet-test' });
    const result = await client.replies('1');

    expect(result.success).toBe(true);
    expect(result.tweets?.[0].id).toBe('2');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/api/trpc/tweets.getConversation');
    const params = new URL(url as string).searchParams.get('input');
    expect(params).toBe(JSON.stringify({ tweetId: '1', force: 'true' }));
    expect((init as RequestInit).headers).toMatchObject({ authorization: 'Bearer sweet-test' });
  });

  it('fetches thread', async () => {
    const conversationPayload = {
      tweetIds: ['1', '2'],
      tweets: {
        1: { id: '1', text: 'root', author: { username: 'root', name: 'Root' }, conversationId: 'c1' },
        2: { id: '2', text: 'reply', author: { username: 'reply', name: 'Reply' }, conversationId: 'c1' },
      },
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        result: { data: conversationPayload },
      }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const client = new SweetisticsClient({ baseUrl: 'https://api.example.com', apiKey: 'sweet-test' });
    const result = await client.thread('1');

    expect(result.success).toBe(true);
    expect(result.tweets?.length).toBe(2);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/api/trpc/tweets.getConversation');
    const params = new URL(url as string).searchParams.get('input');
    expect(params).toBe(JSON.stringify({ tweetId: '1', force: 'true' }));
    expect((init as RequestInit).headers).toMatchObject({ authorization: 'Bearer sweet-test' });
  });

  it('searches tweets', async () => {
    const searchPayload = {
      tweets: {
        items: [
          {
            id: '3',
            text: 'needle',
            authorUsername: 'n',
            authorName: 'Needle',
            createdAt: '2024-01-01',
            metrics: { replyCount: 1, retweetCount: 2, likeCount: 3 },
          },
        ],
      },
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [{ result: { data: searchPayload } }],
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const client = new SweetisticsClient({ baseUrl: 'https://api.example.com', apiKey: 'sweet-test' });
    const result = await client.search('needle', 5);

    expect(result.success).toBe(true);
    expect(result.tweets?.[0].id).toBe('3');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/api/trpc/search.execute');
    expect((init as RequestInit).headers).toMatchObject({ authorization: 'Bearer sweet-test' });
  });

  it('fetches current user', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [{ result: { data: { json: { id: 'u1', username: 'tester', name: 'Test User' } } } }],
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const client = new SweetisticsClient({ baseUrl: 'https://api.example.com', apiKey: 'sweet-test' });
    const result = await client.getCurrentUser();

    expect(result.success).toBe(true);
    expect(result.user?.id).toBe('u1');
    expect(result.user?.username).toBe('tester');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('https://api.example.com/api/trpc/user.getCurrent?batch=1');
    expect((init as RequestInit).headers).toMatchObject({ authorization: 'Bearer sweet-test' });
  });

  it('falls back to GET when POST is not allowed', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 405, json: async () => ({}) })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ result: { data: { json: { id: 'u2', username: 'fallback' } } } }),
      });

    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const client = new SweetisticsClient({ baseUrl: 'https://api.example.com', apiKey: 'sweet-test' });
    const result = await client.getCurrentUser();

    expect(result.success).toBe(true);
    expect(result.user?.id).toBe('u2');
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1][0]).toContain('input=null');
  });

  it('propagates Sweetistics user errors', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [{ result: { error: { message: 'bad key' } } }],
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const client = new SweetisticsClient({ baseUrl: 'https://api.example.com', apiKey: 'sweet-test' });
    const result = await client.getCurrentUser();

    expect(result.success).toBe(false);
    expect(result.error).toBe('bad key');
  });

  it('propagates Sweetistics error message', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 500,
      json: async () => [{ error: { message: 'boom' } }],
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const client = new SweetisticsClient({ baseUrl: 'https://api.example.com', apiKey: 'sweet-test' });
    const result = await client.search('needle', 1);

    expect(result.success).toBe(false);
    expect(result.error).toBe('boom');
  });
});
