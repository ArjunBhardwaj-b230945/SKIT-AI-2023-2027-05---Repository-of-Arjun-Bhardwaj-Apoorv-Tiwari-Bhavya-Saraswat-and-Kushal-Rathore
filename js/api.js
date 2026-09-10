/**
 * TaxSathi – API Configuration & Fetch Utility
 * ---------------------------------------------
 * Centralises the backend base URL so it can be changed
 * in exactly ONE place when the deployed URL is available.
 *
 * Usage:
 *   import { apiPost } from './api.js';
 *   const data = await apiPost('/signin', { email, password });
 */

'use strict';

/* ── Base URL ─────────────────────────────────────
   Change this ONE value when the backend moves to
   a production / staging URL.
   ─────────────────────────────────────────────── */
export const API_BASE_URL = 'http://localhost:3000';

/* ── Endpoints (for reference / auto-complete) ── */
export const ENDPOINTS = {
  SIGNIN: '/signin',
  SIGNUP: '/signup',
};

/**
 * Makes a POST request to the TaxSathi backend.
 *
 * @param {string} endpoint  - e.g. '/signin'
 * @param {object} body      - Plain JS object; will be JSON-serialised
 * @returns {Promise<{ ok: boolean, status: number, data: object }>}
 *
 * Throws only on genuine network failures (no internet, CORS hard-block, etc.)
 * HTTP error status codes (400, 401, 409…) are returned as resolved values
 * so the caller can display appropriate messages without try/catch nesting.
 */
export async function apiPost(endpoint, body) {
  const url = `${API_BASE_URL}${endpoint}`;

  let response;
  try {
    response = await fetch(url, {
      method:  'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept':       'application/json',
      },
      body: JSON.stringify(body),
    });
  } catch (networkError) {
    // fetch() only throws on genuine network failures
    // (no server, DNS failure, CORS preflight hard-blocked, etc.)
    throw new NetworkError(
      'Unable to reach the server. Please check that the backend is running at ' +
      API_BASE_URL + ' and that CORS is configured correctly.'
    );
  }

  // Parse JSON body — guard against non-JSON responses (e.g. HTML error pages)
  let data = {};
  try {
    data = await response.json();
  } catch (_) {
    data = { message: response.statusText || 'Unknown server response' };
  }

  return {
    ok:     response.ok,          // true for 2xx
    status: response.status,
    data,
  };
}

/**
 * Custom error class for network-level failures
 * (distinct from HTTP error responses).
 */
export class NetworkError extends Error {
  constructor(message) {
    super(message);
    this.name = 'NetworkError';
  }
}
