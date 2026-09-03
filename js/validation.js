/**
 * TaxSathi – Shared Form Validation Utilities
 * -------------------------------------------
 * Pure functions for validating common form fields.
 * No DOM side-effects here; all DOM work is in page-specific JS.
 */

'use strict';

/* ── Validation Rules ─────────────────────────── */

/**
 * Returns true if value is not empty / whitespace.
 * @param {string} value
 * @returns {boolean}
 */
export function isRequired(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

/**
 * Returns true if value is a valid email address.
 * @param {string} value
 * @returns {boolean}
 */
export function isValidEmail(value) {
  // RFC 5322-inspired simplified regex — covers common valid addresses
  const re = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
  return re.test(String(value).toLowerCase().trim());
}

/**
 * Returns true if password meets minimum requirements.
 * Min 8 chars, at least 1 uppercase, 1 lowercase, 1 digit.
 * @param {string} value
 * @returns {boolean}
 */
export function isValidPassword(value) {
  if (typeof value !== 'string' || value.length < 8) return false;
  const hasUpper  = /[A-Z]/.test(value);
  const hasLower  = /[a-z]/.test(value);
  const hasDigit  = /\d/.test(value);
  return hasUpper && hasLower && hasDigit;
}

/**
 * Calculates password strength score (1–4).
 * 1 = Weak, 2 = Fair, 3 = Good, 4 = Strong
 * @param {string} value
 * @returns {{ score: number, label: string, color: string }}
 */
export function passwordStrength(value) {
  if (!value || value.length === 0) return { score: 0, label: '', color: '' };

  let score = 0;
  if (value.length >= 8)  score++;
  if (/[A-Z]/.test(value)) score++;
  if (/\d/.test(value))    score++;
  if (/[^A-Za-z0-9]/.test(value) || value.length >= 12) score++;

  const labels = ['', 'Weak', 'Fair', 'Good', 'Strong'];
  const colors = ['', '#D32F2F', '#E65100', '#D4920A', '#2E7D32'];

  return { score, label: labels[score], color: colors[score] };
}

/**
 * Returns true if two password values match.
 * @param {string} password
 * @param {string} confirm
 * @returns {boolean}
 */
export function passwordsMatch(password, confirm) {
  return password === confirm;
}

/**
 * Returns true if name contains at least 2 characters and only valid chars.
 * @param {string} value
 * @returns {boolean}
 */
export function isValidName(value) {
  const v = typeof value === 'string' ? value.trim() : '';
  return v.length >= 2 && /^[A-Za-z\u0900-\u097F\s'-]+$/.test(v);
}

/* ── DOM Helpers ──────────────────────────────── */

/**
 * Shows a field-level error message.
 * @param {HTMLElement} field     - The input element
 * @param {HTMLElement} errorEl   - The error display element
 * @param {string}      message   - Error message text
 */
export function showFieldError(field, errorEl, message) {
  field.classList.remove('is-valid');
  field.classList.add('is-invalid');
  field.setAttribute('aria-invalid', 'true');
  // Target inner <span> to preserve the SVG icon sibling
  const textNode = errorEl.querySelector('span') || errorEl;
  textNode.textContent = message;
  errorEl.classList.add('is-visible');
}

/**
 * Clears a field-level error, optionally marks as valid.
 * @param {HTMLElement} field
 * @param {HTMLElement} errorEl
 * @param {boolean}     [markValid=true]
 */
export function clearFieldError(field, errorEl, markValid = true) {
  field.classList.remove('is-invalid');
  field.removeAttribute('aria-invalid');
  errorEl.classList.remove('is-visible');
  if (markValid) {
    field.classList.add('is-valid');
  } else {
    field.classList.remove('is-valid');
  }
}

/**
 * Resets a field to its neutral (untouched) state.
 * @param {HTMLElement} field
 * @param {HTMLElement} errorEl
 */
export function resetField(field, errorEl) {
  field.classList.remove('is-invalid', 'is-valid');
  field.removeAttribute('aria-invalid');
  errorEl.classList.remove('is-visible');
  const textNode = errorEl.querySelector('span') || errorEl;
  textNode.textContent = '';
}

/**
 * Sets the button into a loading state.
 * @param {HTMLButtonElement} btn
 */
export function setButtonLoading(btn) {
  btn.disabled = true;
  btn.classList.add('is-loading');
  btn.setAttribute('aria-busy', 'true');
}

/**
 * Restores button from loading state.
 * @param {HTMLButtonElement} btn
 */
export function clearButtonLoading(btn) {
  btn.disabled = false;
  btn.classList.remove('is-loading');
  btn.removeAttribute('aria-busy');
}
