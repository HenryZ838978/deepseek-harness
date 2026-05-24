// Phone + OTP login screen. Chinese UI.
// Falls back to mock OTP "123456" when backend is unreachable so the demo runs offline.

import { $, el, toast } from './util.js';
import { sendOTP, login } from './api.js';

const MOCK_OTP = '123456';
const MOCK_TOKEN = 'mock.demo.token';

export function renderLogin(root, { navigate }) {
  const phoneInput = el('input', {
    type: 'tel',
    inputMode: 'numeric',
    placeholder: '手机号',
    maxlength: 11,
    autocomplete: 'tel',
  });
  const otpInput = el('input', {
    type: 'tel',
    inputMode: 'numeric',
    placeholder: '6 位验证码',
    maxlength: 6,
    autocomplete: 'one-time-code',
  });

  const otpBtn = el('button', { class: 'otp-btn', type: 'button' }, '发送验证码');
  const submitBtn = el('button', { class: 'btn-primary', type: 'submit', disabled: true }, '登 录');

  let countdownTimer = null;

  function updateSubmit() {
    submitBtn.disabled = !(isValidPhone(phoneInput.value) && otpInput.value.length === 6);
  }
  phoneInput.addEventListener('input', () => {
    phoneInput.value = phoneInput.value.replace(/\D/g, '').slice(0, 11);
    updateSubmit();
  });
  otpInput.addEventListener('input', () => {
    otpInput.value = otpInput.value.replace(/\D/g, '').slice(0, 6);
    updateSubmit();
  });

  otpBtn.addEventListener('click', async () => {
    const phone = phoneInput.value.trim();
    if (!isValidPhone(phone)) {
      toast('请输入正确的 11 位手机号', 'err');
      phoneInput.focus();
      return;
    }
    otpBtn.disabled = true;
    try {
      await sendOTP('+86' + phone);
      toast('验证码已发送', 'ok');
    } catch (e) {
      // Backend unreachable / 404 — fall back to mock mode for demo.
      toast('演示模式：验证码为 123456', '');
    }
    startCountdown(60);
  });

  function startCountdown(sec) {
    let n = sec;
    otpBtn.disabled = true;
    otpBtn.textContent = n + 's';
    clearInterval(countdownTimer);
    countdownTimer = setInterval(() => {
      n -= 1;
      if (n <= 0) {
        clearInterval(countdownTimer);
        otpBtn.disabled = false;
        otpBtn.textContent = '重新发送';
      } else {
        otpBtn.textContent = n + 's';
      }
    }, 1000);
  }

  const form = el('form', { class: 'login', onSubmit: async (e) => {
    e.preventDefault();
    if (submitBtn.disabled) return;
    const phone = phoneInput.value.trim();
    const otp = otpInput.value.trim();
    submitBtn.disabled = true;
    submitBtn.textContent = '登录中...';
    try {
      let token;
      try {
        const r = await login('+86' + phone, otp);
        token = r && r.token;
      } catch (err) {
        // Offline/demo fallback: accept the mock OTP only.
        if (otp === MOCK_OTP) {
          token = MOCK_TOKEN;
        } else {
          throw err;
        }
      }
      if (!token) throw new Error('登录失败');
      localStorage.setItem('token', token);
      localStorage.setItem('phone', phone);
      clearInterval(countdownTimer);
      toast('登录成功', 'ok');
      navigate('chat');
    } catch (err) {
      toast(friendlyAuthError(err), 'err');
      submitBtn.disabled = false;
      submitBtn.textContent = '登 录';
    }
  }},
    el('div', { class: 'login-header' },
      el('h1', {}, '深 求'),
      el('p',  {}, 'DeepSeek Harness'),
    ),
    el('div', { class: 'field' },
      el('span', { class: 'prefix' }, '+86'),
      phoneInput,
    ),
    el('div', { class: 'field' },
      otpInput,
      otpBtn,
    ),
    submitBtn,
    el('div', { class: 'login-foot' },
      '登录即代表同意 ',
      el('a', { href: '#', onClick: (e) => e.preventDefault() }, '《用户协议》'),
      ' 与 ',
      el('a', { href: '#', onClick: (e) => e.preventDefault() }, '《隐私政策》'),
      el('br'),
      '演示模式验证码：123456',
    ),
  );

  root.appendChild(form);
  // Pre-fill remembered phone if available.
  const saved = localStorage.getItem('phone');
  if (saved) { phoneInput.value = saved; updateSubmit(); }
}

function isValidPhone(p) {
  return /^1[3-9]\d{9}$/.test(String(p || '').trim());
}

function friendlyAuthError(err) {
  const code = err && err.code;
  if (code === 'http_401' || code === 'auth_expired') return '验证码错误或已过期';
  if (code === 'http_429') return '请求过于频繁，请稍后重试';
  return (err && err.message) || '登录失败，请重试';
}
