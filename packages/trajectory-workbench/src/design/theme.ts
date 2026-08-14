export type ResolvedTheme = 'dark' | 'light';

export const themeStorageKey = 'trajectory-workbench.theme';

export function readThemePreference(): ResolvedTheme | null {
  try {
    const saved = window.localStorage.getItem(themeStorageKey);
    return saved === 'dark' || saved === 'light' ? saved : null;
  } catch {
    return null;
  }
}

export function systemTheme(): ResolvedTheme {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export function saveThemePreference(theme: ResolvedTheme) {
  try {
    window.localStorage.setItem(themeStorageKey, theme);
  } catch {
    // A disabled or full storage area must not prevent the workbench loading.
  }
}
