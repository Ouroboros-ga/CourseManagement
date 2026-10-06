<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useSessionStore } from '../stores/session'
import { ElMessage } from 'element-plus'

const router = useRouter()
const sessionStore = useSessionStore()

const username = ref('')
const password = ref('')
const loading = ref(false)
const errorMessage = ref('')

async function handleLogin() {
  if (!username.value || !password.value) {
    errorMessage.value = '请输入用户名与密码'
    return
  }
  loading.value = true
  errorMessage.value = ''
  try {
    await sessionStore.signIn(username.value, password.value)
    ElMessage.success('登录成功')
    router.push('/dashboard/schedule')
  } catch (err: unknown) {
    if (err && typeof err === 'object' && 'message' in err) {
      errorMessage.value = String(err.message)
    } else {
      errorMessage.value = '登录失败，请检查账号密码'
    }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <!-- 左侧品牌叙事栏 -->
    <div class="login-left">
      <div class="login-brand font-mono">COURSECHECK · ADMIN CONSOLE</div>
      <div class="login-hero">
        <div class="issue font-mono">VOL.04 — 2026 秋季学期</div>
        <h1 class="font-serif">查课管理<br />工作台</h1>
        <p>
          面向高校教学管理的线下查课排班、现场留痕与考勤闭环平台。
          以编辑级的信息密度，呈现每一堂课的真实状态。
        </p>
      </div>
      <div class="login-meta">
        <div>
          <span class="num font-mono">112</span>
          <span>API 接口契约</span>
        </div>
        <div>
          <span class="num font-mono">18</span>
          <span>覆盖教学班</span>
        </div>
        <div>
          <span class="num font-mono">97.4%</span>
          <span>本周到课率</span>
        </div>
      </div>
    </div>

    <!-- 右侧登录表单 -->
    <div class="login-right">
      <div class="login-form">
        <div class="form-tag font-mono">SIGN IN / 身份验证</div>
        <h2 class="font-serif">欢迎回来</h2>

        <div v-if="errorMessage" class="login-error">{{ errorMessage }}</div>

        <form @submit.prevent="handleLogin">
          <div class="field">
            <label>管理账号（工号 / 学号）</label>
            <input
              v-model="username"
              type="text"
              required
              autocomplete="username"
              placeholder="请输入管理员账号"
            />
          </div>
          <div class="field">
            <label>登录密码</label>
            <input
              v-model="password"
              type="password"
              required
              autocomplete="current-password"
              placeholder="请输入密码"
            />
          </div>
          <button type="submit" class="btn btn-dark login-submit" :disabled="loading">
            <span v-if="loading">正在验证身份…</span>
            <span v-else>进入工作台 →</span>
          </button>
        </form>

        <div class="login-foot">
          Web 访问令牌仅留存于内存，会话安全由 HttpOnly Cookie 保障。<br />
          登录即代表同意《教学数据管理规范》与《隐私保护协议》。
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-wrap {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 1fr 1fr;
}

.login-left {
  background: var(--ink);
  color: var(--paper);
  padding: 64px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  position: relative;
  overflow: hidden;
}
.login-left::after {
  content: '';
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(250, 248, 245, 0.02) 1px, transparent 1px),
    linear-gradient(90deg, rgba(250, 248, 245, 0.02) 1px, transparent 1px);
  background-size: 48px 48px;
  pointer-events: none;
}
.login-brand {
  font-size: 12px;
  letter-spacing: 0.15em;
  opacity: 0.5;
}
.login-hero { position: relative; z-index: 1; }
.login-hero .issue {
  font-size: 12px;
  color: var(--accent);
  letter-spacing: 0.1em;
  margin-bottom: 24px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.login-hero .issue::before {
  content: '';
  width: 32px;
  height: 1px;
  background: var(--accent);
}
.login-hero h1 {
  font-size: clamp(36px, 4vw, 52px);
  font-weight: 700;
  line-height: 1.25;
  letter-spacing: 0.02em;
  margin-bottom: 24px;
}
.login-hero p {
  font-size: 15px;
  line-height: 1.9;
  opacity: 0.55;
  max-width: 400px;
  font-weight: 300;
}
.login-meta {
  display: flex;
  gap: 48px;
  font-size: 12px;
  opacity: 0.4;
  position: relative;
  z-index: 1;
}
.login-meta span { display: block; }
.login-meta .num {
  font-size: 24px;
  font-weight: 600;
  opacity: 1;
  color: var(--paper);
  margin-bottom: 4px;
}

.login-right {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 64px;
}
.login-form { width: 100%; max-width: 380px; }
.form-tag {
  font-size: 11px;
  color: var(--ink-mute);
  letter-spacing: 0.1em;
  margin-bottom: 8px;
}
.login-form h2 { font-size: 28px; font-weight: 600; margin-bottom: 40px; }

.login-error {
  padding: 12px 16px;
  margin-bottom: 24px;
  background: var(--accent-soft);
  border-left: 2px solid var(--accent);
  font-size: 12px;
  color: var(--accent);
  font-weight: 500;
}

.field { margin-bottom: 24px; }
.field label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-soft);
  margin-bottom: 8px;
  letter-spacing: 0.03em;
}
.field input {
  width: 100%;
  padding: 12px 0;
  border: none;
  border-bottom: 1px solid var(--line-strong);
  background: transparent;
  font-size: 15px;
  font-family: inherit;
  color: var(--ink);
  outline: none;
  transition: border-color 0.2s;
}
.field input:focus { border-bottom-color: var(--ink); }
.field input::placeholder { color: var(--ink-mute); font-weight: 300; }

.login-submit { width: 100%; padding: 14px; justify-content: center; margin-top: 8px; }

.login-foot {
  margin-top: 40px;
  padding-top: 24px;
  border-top: 1px solid var(--line);
  font-size: 11px;
  color: var(--ink-mute);
  line-height: 1.8;
}

@media (max-width: 900px) {
  .login-wrap { grid-template-columns: 1fr; }
  .login-left { display: none; }
}
</style>
