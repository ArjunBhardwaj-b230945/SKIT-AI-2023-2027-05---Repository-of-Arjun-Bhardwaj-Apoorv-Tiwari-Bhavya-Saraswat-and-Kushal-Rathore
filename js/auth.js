/**
 * TaxSathi – Authentication / Session Utility
 * --------------------------------------------
 * Centralises all JWT token storage so the rest of the
 * application never touches localStorage directly.
 *
 * Designed to be easy to upgrade later:
 *   - swap localStorage for sessionStorage → change ONE function
 *   - add token-expiry checking → add ONE helper
 *   - add refresh-token logic → extend getToken()
 *
 * Usage:
 *   import { saveToken, isLoggedIn, removeToken } from './auth.js';
 */

'use strict';

/* ── Storage key (change here if key name needs updating) ── */
const TOKEN_KEY = 'taxsathi_token';

/**
 * Persists the JWT returned by the backend.
 * @param {string} token - Raw JWT string from API response
 */
export function saveToken(token) {
  if (!token || typeof token !== 'string') {
    console.warn('[TaxSathi Auth] saveToken: received invalid token, not saving.');
    return;
  }
  localStorage.setItem(TOKEN_KEY, token);
}

/**
 * Retrieves the stored JWT, or null if not present.
 * @returns {string|null}
 */
export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

/**
 * Removes the stored JWT (used on logout).
 */
export function removeToken() {
  localStorage.removeItem(TOKEN_KEY);
}

/**
 * Returns true if a token is currently stored.
 * Does NOT validate the token signature or expiry
 * (that is the backend's responsibility on every request).
 * @returns {boolean}
 */
export function isLoggedIn() {
  return Boolean(getToken());
}

/**
 * Signs the user out: removes the token and redirects to login.
 * Call this from the Dashboard / any protected page.
 */
export function signOut() {
  removeToken();
  window.location.href = 'login.html';
}
