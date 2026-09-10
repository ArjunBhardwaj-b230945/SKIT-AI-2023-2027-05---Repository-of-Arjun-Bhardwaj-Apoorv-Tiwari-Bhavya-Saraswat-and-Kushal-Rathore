/**
 * TaxSathi – Register Page Logic
 * --------------------------------
 * Handles:
 *   - Real-time field validation (on blur / on input after first touch)
 *   - Full-form validation on submit
 *   - Password strength meter
 *   - Password / confirm-password visibility toggles
 *   - Submit button loading state
 *   - Alert banner for global messages
 *   - API call to POST /signup  [Stage 3]
 *   - JWT storage via auth.js   [Stage 3]
 *   - Already-logged-in redirect [Stage 4]
 */

'use strict';

import {
  isRequired,
  isValidEmail,
  isValidPassword,
  isValidName,
  passwordStrength,
  passwordsMatch,
  showFieldError,
  clearFieldError,
  setButtonLoading,
  clearButtonLoading,
} from './validation.js';

/* ── Stage 3: API & Auth utilities ───────────── */
import { apiPost, ENDPOINTS, NetworkError } from './api.js';
import { saveToken, isLoggedIn }            from './auth.js';

/* ── Stage 4: Redirect already-authenticated users ─
   If a token exists, skip the register page entirely. */
if (isLoggedIn()) {
  window.location.replace('dashboard.html');
}

/* ── Element references ───────────────────────── */
const form              = document.getElementById('registerForm');

const firstNameInput    = document.getElementById('regFirstName');
const firstNameError    = document.getElementById('regFirstNameError');
const lastNameInput     = document.getElementById('regLastName');
const lastNameError     = document.getElementById('regLastNameError');
const emailInput        = document.getElementById('regEmail');
const emailError        = document.getElementById('regEmailError');
const passInput         = document.getElementById('regPassword');
const passError         = document.getElementById('regPasswordError');
const passToggle        = document.getElementById('regPassToggle');
const confirmInput      = document.getElementById('regConfirmPassword');
const confirmError      = document.getElementById('regConfirmPasswordError');
const confirmToggle     = document.getElementById('regConfirmPassToggle');
const termsCheck        = document.getElementById('regTerms');
const termsError        = document.getElementById('regTermsError');
const submitBtn         = document.getElementById('registerSubmit');
const alertBanner       = document.getElementById('registerAlert');
const alertMsg          = document.getElementById('registerAlertMsg');

// Strength meter
const strengthFill      = document.getElementById('strengthFill');
const strengthLabel     = document.getElementById('strengthLabel');

/* ── Touched tracking ─────────────────────────── */
const touched = {
  firstName: false, lastName: false,
  email: false, password: false,
  confirm: false, terms: false,
};

/* ── Individual validators ────────────────────── */
function validateFirstName() {
  const v = firstNameInput.value;
  if (!isRequired(v)) {
    showFieldError(firstNameInput, firstNameError, 'First name is required.');
    return false;
  }
  if (!isValidName(v)) {
    showFieldError(firstNameInput, firstNameError,
      'Enter a valid first name (min 2 characters, letters only).');
    return false;
  }
  clearFieldError(firstNameInput, firstNameError, true);
  return true;
}

function validateLastName() {
  const v = lastNameInput.value;
  if (!isRequired(v)) {
    showFieldError(lastNameInput, lastNameError, 'Last name is required.');
    return false;
  }
  if (!isValidName(v)) {
    showFieldError(lastNameInput, lastNameError,
      'Enter a valid last name (min 2 characters, letters only).');
    return false;
  }
  clearFieldError(lastNameInput, lastNameError, true);
  return true;
}

function validateEmail() {
  const v = emailInput.value;
  if (!isRequired(v)) {
    showFieldError(emailInput, emailError, 'Email address is required.');
    return false;
  }
  if (!isValidEmail(v)) {
    showFieldError(emailInput, emailError, 'Please enter a valid email address.');
    return false;
  }
  clearFieldError(emailInput, emailError, true);
  return true;
}

function validatePassword() {
  const v = passInput.value;
  if (!isRequired(v)) {
    showFieldError(passInput, passError, 'Password is required.');
    return false;
  }
  if (!isValidPassword(v)) {
    showFieldError(passInput, passError,
      'Use at least 8 characters with uppercase, lowercase and a number.');
    return false;
  }
  clearFieldError(passInput, passError, true);
  return true;
}

function validateConfirm() {
  const v = confirmInput.value;
  if (!isRequired(v)) {
    showFieldError(confirmInput, confirmError, 'Please confirm your password.');
    return false;
  }
  if (!passwordsMatch(passInput.value, v)) {
    showFieldError(confirmInput, confirmError, 'Passwords do not match.');
    return false;
  }
  clearFieldError(confirmInput, confirmError, true);
  return true;
}

function validateTerms() {
  if (!termsCheck.checked) {
    termsError.classList.add('is-visible');
    return false;
  }
  termsError.classList.remove('is-visible');
  return true;
}

/* ── Password strength meter update ───────────── */
function updateStrengthMeter(value) {
  const { score, label, color } = passwordStrength(value);
  strengthFill.setAttribute('data-strength', score);
  strengthFill.style.width = score ? `${score * 25}%` : '0%';
  strengthFill.style.backgroundColor = color;
  strengthLabel.textContent = label ? `Password strength: ${label}` : '';
  strengthLabel.style.color = color;
}

/* ── Alert helpers ────────────────────────────── */
function showAlert(message, type = 'error') {
  alertMsg.textContent = message;
  alertBanner.classList.remove('alert-error', 'alert-success');
  alertBanner.classList.add(`alert-${type}`, 'is-visible');
  alertBanner.focus();
}

function hideAlert() {
  alertBanner.classList.remove('is-visible');
}

/* ── Password visibility toggles ─────────────── */
function bindPasswordToggle(toggleBtn, inputEl) {
  toggleBtn.addEventListener('click', () => {
    const isVisible = inputEl.type === 'text';
    inputEl.type = isVisible ? 'password' : 'text';
    toggleBtn.setAttribute('aria-label', isVisible ? 'Show password' : 'Hide password');
    toggleBtn.innerHTML = isVisible ? eyeIcon() : eyeOffIcon();
  });
}

bindPasswordToggle(passToggle, passInput);
bindPasswordToggle(confirmToggle, confirmInput);

/* ── Real-time event bindings ─────────────────── */
function bindField(input, touchKey, validator, extraOnInput) {
  input.addEventListener('blur', () => {
    touched[touchKey] = true;
    validator();
  });
  input.addEventListener('input', () => {
    hideAlert();
    if (touched[touchKey]) validator();
    if (extraOnInput) extraOnInput(input.value);
  });
}

bindField(firstNameInput, 'firstName', validateFirstName);
bindField(lastNameInput,  'lastName',  validateLastName);
bindField(emailInput,     'email',     validateEmail);
bindField(passInput,      'password',  validatePassword, updateStrengthMeter);

// Confirm password: also re-validate if it was already touched
bindField(confirmInput, 'confirm', validateConfirm);
passInput.addEventListener('input', () => {
  if (touched.confirm) validateConfirm();
});

termsCheck.addEventListener('change', () => {
  if (touched.terms) validateTerms();
});

/* ── Form submit ──────────────────────────────── */
form.addEventListener('submit', async (e) => {
  e.preventDefault();
  hideAlert();

  // Touch all fields
  Object.keys(touched).forEach(k => { touched[k] = true; });

  const ok = [
    validateFirstName(),
    validateLastName(),
    validateEmail(),
    validatePassword(),
    validateConfirm(),
    validateTerms(),
  ].every(Boolean);

  if (!ok) {
    const firstInvalid = form.querySelector('.form-control.is-invalid');
    if (firstInvalid) firstInvalid.focus();
    return;
  }

  // ── Stage 3: Call POST /signup ──────────────
  setButtonLoading(submitBtn);

  try {
    const { ok: httpOk, status, data } = await apiPost(ENDPOINTS.SIGNUP, {
      email:    emailInput.value.trim(),
      password: passInput.value,
    });

    if (httpOk && status === 201) {
      // ✅ Success — persist JWT and navigate to dashboard
      saveToken(data.token);
      showAlert('Account created successfully! Redirecting…', 'success');
      setTimeout(() => { window.location.href = 'dashboard.html'; }, 800);
      return; // keep button disabled during redirect
    }

    // ── HTTP error responses ─────────────────
    if (status === 400) {
      showAlert('Email and password are required.', 'error');
    } else if (status === 409) {
      showAlert(
        'An account with this email already exists. Try signing in instead.',
        'error'
      );
    } else {
      const msg = data?.message || 'Something went wrong. Please try again shortly.';
      showAlert(msg, 'error');
    }

  } catch (err) {
    if (err.name === 'NetworkError') {
      showAlert(
        'Unable to connect to the server. ' +
        'Please ensure the backend is running and try again.',
        'error'
      );
    } else {
      showAlert('An unexpected error occurred. Please try again.', 'error');
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
