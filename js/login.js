/**
 * TaxSathi – Login Page Logic
 * ---------------------------
 * Handles:
 *   - Real-time field validation (on blur / on input after first touch)
 *   - Full-form validation on submit
 *   - Password visibility toggle
 *   - Submit button loading state
 *   - Alert banner for global errors
 *   - API call to POST /signin  [Stage 3]
 *   - JWT storage via auth.js   [Stage 3]
 *   - Already-logged-in redirect [Stage 4]
 */

'use strict';

import {
  isRequired,
  isValidEmail,
  showFieldError,
  clearFieldError,
  setButtonLoading,
  clearButtonLoading,
} from './validation.js';

/* ── Stage 3: API & Auth utilities ───────────── */
import { apiPost, ENDPOINTS, NetworkError } from './api.js';
import { saveToken, isLoggedIn }            from './auth.js';

/* ── Stage 4: Redirect already-authenticated users ─
   If a token exists, skip the login page entirely.   */
if (isLoggedIn()) {
  window.location.replace('dashboard.html');
}

/* ── Element references ───────────────────────── */
const form         = document.getElementById('loginForm');
const emailInput   = document.getElementById('loginEmail');
const emailError   = document.getElementById('loginEmailError');
const passInput    = document.getElementById('loginPassword');
const passError    = document.getElementById('loginPasswordError');
const passToggle   = document.getElementById('loginPassToggle');
const submitBtn    = document.getElementById('loginSubmit');
const alertBanner  = document.getElementById('loginAlert');
const alertMsg     = document.getElementById('loginAlertMsg');

/* ── Tracking which fields have been touched ──── */
const touched = { email: false, password: false };

/* ── Validate email field ─────────────────────── */
function validateEmail() {
  const val = emailInput.value;
  if (!isRequired(val)) {
    showFieldError(emailInput, emailError, 'Email address is required.');
    return false;
  }
  if (!isValidEmail(val)) {
    showFieldError(emailInput, emailError, 'Please enter a valid email address.');
    return false;
  }
  clearFieldError(emailInput, emailError, true);
  return true;
}

/* ── Validate password field (login: presence-only) ──
   On login, only check that the field is not empty.
   Password complexity is the backend's responsibility —
   enforcing it here would prevent users with legacy or
   simpler passwords from signing in at all.           */
function validatePassword() {
  const val = passInput.value;
  if (!isRequired(val)) {
    showFieldError(passInput, passError, 'Password is required.');
    return false;
  }
  clearFieldError(passInput, passError, true);
  return true;
}


/* ── Show / hide global alert ─────────────────── */
function showAlert(message) {
  alertMsg.textContent = message;
  alertBanner.classList.add('is-visible');
  alertBanner.focus();
}

function hideAlert() {
  alertBanner.classList.remove('is-visible');
}

/* ── Password visibility toggle ───────────────── */
passToggle.addEventListener('click', () => {
  const isVisible = passInput.type === 'text';
  passInput.type = isVisible ? 'password' : 'text';
  passToggle.setAttribute('aria-label', isVisible ? 'Show password' : 'Hide password');
  passToggle.innerHTML = isVisible ? eyeIcon() : eyeOffIcon();
});

/* ── Real-time validation (blur + input after touch) */
emailInput.addEventListener('blur', () => {
  touched.email = true;
  validateEmail();
});

emailInput.addEventListener('input', () => {
  if (touched.email) validateEmail();
  hideAlert();
});

passInput.addEventListener('blur', () => {
  touched.password = true;
  validatePassword();
});

passInput.addEventListener('input', () => {
  if (touched.password) validatePassword();
  hideAlert();
});

/* ── Form submit ──────────────────────────────── */
form.addEventListener('submit', async (e) => {
  e.preventDefault();
  hideAlert();

  // Mark all as touched
  touched.email    = true;
  touched.password = true;

  const emailOk = validateEmail();
  const passOk  = validatePassword();

  if (!emailOk || !passOk) {
    if (!emailOk) emailInput.focus();
    else passInput.focus();
    return;
  }

  // ── Stage 3: Call POST /signin ──────────────
  setButtonLoading(submitBtn);

  try {
    const { ok, status, data } = await apiPost(ENDPOINTS.SIGNIN, {
      email:    emailInput.value.trim(),
      password: passInput.value,
    });

    if (ok && status === 200) {
      // ✅ Success — persist JWT and navigate to dashboard
      saveToken(data.token);
      alertBanner.classList.remove('alert-error');
      alertBanner.classList.add('alert-success');
      showAlert('Sign-in successful! Redirecting…');
      // Brief pause so user sees the confirmation before redirect
      setTimeout(() => { window.location.href = 'dashboard.html'; }, 800);
      return; // keep button disabled during redirect
    }

    // ── HTTP error responses ─────────────────
    if (status === 400) {
      showAlert('Email and password are required.');
    } else if (status === 401) {
      showAlert('Incorrect email or password. Please try again.');
    } else {
      // Unexpected HTTP status (5xx, etc.)
      const msg = data?.message || 'Something went wrong. Please try again shortly.';
      showAlert(msg);
    }

  } catch (err) {
    if (err.name === 'NetworkError') {
      showAlert(
        'Unable to connect to the server. ' +
        'Please ensure the backend is running and try again.'
      );
    } else {
      showAlert('An unexpected error occurred. Please try again.');
    }
  } finally {
    clearButtonLoading(submitBtn);
  }
});


/* ── SVG icon helpers ─────────────────────────── */
function eyeIcon() {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
    <circle cx="12" cy="12" r="3"/>
  </svg>`;
}

function eyeOffIcon() {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/>
    <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/>
    <line x1="1" y1="1" x2="23" y2="23"/>
  </svg>`;
}
