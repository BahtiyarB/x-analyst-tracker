import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Mock child_process.execSync to prevent actual shell commands
vi.mock('node:child_process', () => ({
  execSync: vi.fn(() => ''),
}));

// Mock fs to prevent actual file operations
vi.mock('node:fs', () => {
  const fs = vi.importActual<typeof import('node:fs')>('node:fs');
  return {
    ...fs,
    existsSync: vi.fn(() => false),
    copyFileSync: vi.fn(),
    mkdtempSync: vi.fn(() => '/tmp/test-dir'),
    readdirSync: vi.fn(() => []),
    rmSync: vi.fn(),
  };
});

describe('cookies', () => {
  const originalEnv = process.env;

  beforeEach(() => {
    vi.resetModules();
    process.env = { ...originalEnv };
    // Clear Twitter-related env vars
    process.env.AUTH_TOKEN = undefined;
    process.env.TWITTER_AUTH_TOKEN = undefined;
    process.env.CT0 = undefined;
    process.env.TWITTER_CT0 = undefined;
  });

  afterEach(() => {
    process.env = originalEnv;
    vi.restoreAllMocks();
  });

  describe('resolveCredentials', () => {
    it('uses firefox when enabled and returns cookies', async () => {
      const { resolveCredentials } = await import('../src/lib/cookies.js');
      const fs = await import('node:fs');

      // Firefox present with cookies.sqlite
      (fs.existsSync as unknown as vi.Mock).mockImplementation((path: string) => {
        const lower = path.toLowerCase();
        if (lower.endsWith('cookies.sqlite')) return true;
        if (lower.includes('firefox')) return true;
        return false;
      });
      (fs.readdirSync as unknown as vi.Mock).mockReturnValue([{ isDirectory: () => true, name: 'abc.default-release' }]);
      (fs.copyFileSync as unknown as vi.Mock).mockImplementation(() => {});
      (fs.mkdtempSync as unknown as vi.Mock).mockReturnValue('/tmp/test-dir');

      // sqlite3 output for firefox
      const { execSync } = await import('node:child_process');
      (execSync as unknown as vi.Mock).mockReturnValue('auth_token|firefox_auth\nct0|firefox_ct0');

      const result = await resolveCredentials({ allowFirefox: true, allowChrome: false, firefoxProfile: 'abc.default-release' });

      expect(result.cookies.authToken).toBe('firefox_auth');
      expect(result.cookies.ct0).toBe('firefox_ct0');
      expect(result.cookies.source).toContain('Firefox');
    });

    it('should prioritize CLI arguments over env vars', async () => {
      process.env.AUTH_TOKEN = 'env_auth';
      process.env.CT0 = 'env_ct0';

      const { resolveCredentials } = await import('../src/lib/cookies.js');
      const result = await resolveCredentials({
        authToken: 'cli_auth',
        ct0: 'cli_ct0',
      });

      expect(result.cookies.authToken).toBe('cli_auth');
      expect(result.cookies.ct0).toBe('cli_ct0');
      expect(result.cookies.source).toBe('CLI argument');
    });

    it('should use AUTH_TOKEN env var', async () => {
      process.env.AUTH_TOKEN = 'test_auth_token';
      process.env.CT0 = 'test_ct0';

      const { resolveCredentials } = await import('../src/lib/cookies.js');
      const result = await resolveCredentials({ allowFirefox: false, allowChrome: false });

      expect(result.cookies.authToken).toBe('test_auth_token');
      expect(result.cookies.ct0).toBe('test_ct0');
      expect(result.cookies.source).toBe('env AUTH_TOKEN');
    });

    it('should use TWITTER_AUTH_TOKEN env var as fallback', async () => {
      process.env.TWITTER_AUTH_TOKEN = 'twitter_auth';
      process.env.TWITTER_CT0 = 'twitter_ct0';

      const { resolveCredentials } = await import('../src/lib/cookies.js');
      const result = await resolveCredentials({ allowFirefox: false, allowChrome: false });

      expect(result.cookies.authToken).toBe('twitter_auth');
      expect(result.cookies.ct0).toBe('twitter_ct0');
    });

    it('should trim whitespace from values', async () => {
      process.env.AUTH_TOKEN = '  trimmed_auth  ';
      process.env.CT0 = '  trimmed_ct0  ';

      const { resolveCredentials } = await import('../src/lib/cookies.js');
      const result = await resolveCredentials({});

      expect(result.cookies.authToken).toBe('trimmed_auth');
      expect(result.cookies.ct0).toBe('trimmed_ct0');
    });

    it('should treat empty strings as null', async () => {
      process.env.AUTH_TOKEN = '   ';
      process.env.CT0 = '';

      const { resolveCredentials } = await import('../src/lib/cookies.js');
      const result = await resolveCredentials({ allowFirefox: false, allowChrome: false });

      expect(result.cookies.authToken).toBeNull();
      expect(result.cookies.ct0).toBeNull();
      expect(result.warnings.length).toBeGreaterThan(0);
    });

    it('should warn when credentials are missing', async () => {
      const { resolveCredentials } = await import('../src/lib/cookies.js');
      const result = await resolveCredentials({ allowFirefox: false, allowChrome: false });

      expect(result.warnings).toContain(
        'Missing auth_token - provide via --auth-token, AUTH_TOKEN env var, or login to x.com in Chrome/Firefox',
      );
      expect(result.warnings).toContain(
        'Missing ct0 - provide via --ct0, CT0 env var, or login to x.com in Chrome/Firefox',
      );
    });
  });

  describe('extractCookiesFromChrome', () => {
    it('returns cookies when sqlite yields hex values', async () => {
      const fs = await import('node:fs');
      const { execSync } = await import('node:child_process');
      // Pretend Chrome cookie DB exists
      (fs.existsSync as unknown as vi.Mock).mockImplementation((path: string) => path.includes('Cookies'));
      (fs.copyFileSync as unknown as vi.Mock).mockImplementation(() => {});
      // sqlite output with hex strings ("test_auth", "test_ct0")
      (execSync as unknown as vi.Mock).mockImplementation((cmd: string) => {
        if (cmd.includes('sqlite3')) {
          return 'auth_token|746573745f61757468\nct0|746573745f637430';
        }
        return '';
      });

      const { extractCookiesFromChrome } = await import('../src/lib/cookies.js');
      const result = await extractCookiesFromChrome('Default');

      expect(result.cookies.authToken).toBe('test_auth');
      expect(result.cookies.ct0).toBe('test_ct0');
      expect(result.cookies.source).toContain('Chrome');
      expect(result.warnings).toHaveLength(0);
    });

    it('warns when Chrome DB exists but contains no cookies', async () => {
      const fs = await import('node:fs');
      const { execSync } = await import('node:child_process');
      (fs.existsSync as unknown as vi.Mock).mockImplementation((path: string) => path.includes('Cookies'));
      (fs.copyFileSync as unknown as vi.Mock).mockImplementation(() => {});
      (execSync as unknown as vi.Mock).mockReturnValue('');

      const { extractCookiesFromChrome } = await import('../src/lib/cookies.js');
      const result = await extractCookiesFromChrome('Default');

      expect(result.cookies.authToken).toBeNull();
      expect(result.cookies.ct0).toBeNull();
      expect(result.warnings.some((w) => w.includes('No Twitter cookies found in Chrome'))).toBe(true);
    });
  });
});
