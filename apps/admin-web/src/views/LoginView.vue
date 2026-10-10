<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useSessionStore } from '../stores/session'
import { ElMessage } from 'element-plus'
import schoolLogo from '../assets/school-logo.png'

const router = useRouter()
const sessionStore = useSessionStore()

const username = ref('')
const password = ref('')
const loading = ref(false)
const errorMessage = ref('')

const currentTermText = computed(() => sessionStore.currentSemesterName || '2026-2027 学年第一学期')

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
      <div class="login-brand-header">
        <img :src="schoolLogo" alt="绍兴理工学院校徽" class="brand-school-logo" />
        <div class="brand-text">
          <div class="college-title font-serif">绍兴理工学院 · 人工智能学院</div>
          <div class="college-sub font-mono">SCHOOL OF ARTIFICIAL INTELLIGENCE</div>
        </div>
      </div>

      <div class="login-hero">
        <div class="term-badge font-mono">
          <span class="dot"></span>
          <span>{{ currentTermText }}</span>
        </div>
        <h1 class="font-serif">课堂教学考勤<br />管理工作台</h1>
        <p>
          聚焦高校课堂教学秩序与学风建设，构建“任务生成 — 现场抽查 — 规范留痕 — 异议复核”全流程闭环教学质量监控与考勤保障系统。
        </p>
      </div>

      <div class="login-meta">
        <div>
          <span class="num font-mono">100%</span>
          <span>现场实景留痕</span>
        </div>
        <div>
          <span class="num font-mono">闭环</span>
          <span>双审异议复核</span>
        </div>
        <div>
          <span class="num font-mono">协同</span>
          <span>多端实时互通</span>
        </div>
      </div>
    </div>

    <!-- 右侧登录表单 -->
    <div class="login-right">
      <div class="login-form">
        <!-- 移动端或卡片顶部的学院标识 -->
        <div class="form-header">
          <img :src="schoolLogo" alt="绍兴理工学院校徽" class="form-school-logo" />
          <div class="form-header-text">
            <div class="school-name font-serif">绍兴理工学院 · 人工智能学院</div>
            <div class="platform-name font-mono">TEACHING QUALITY & ATTENDANCE SYSTEM</div>
          </div>
        </div>

        <div class="form-welcome">
          <h2 class="font-serif">管理工作台登录</h2>
          <p class="form-subtitle">欢迎使用教学考勤管理系统，请验证身份以进入系统</p>
        </div>

        <div v-if="errorMessage" class="login-error">{{ errorMessage }}</div>

        <form @submit.prevent="handleLogin">
          <div class="field">
            <label>管理账号（工号 / 登录名）</label>
            <input
              v-model="username"
              type="text"
              required
              autocomplete="username"
              placeholder="请输入管理员或教师账号"
            />
          </div>
          <div class="field">
            <label>登录密码</label>
            <input
              v-model="password"
              type="password"
              required
              autocomplete="current-password"
              placeholder="请输入登录密码"
            />
          </div>
          <button type="submit" class="btn btn-dark login-submit" :disabled="loading">
            <span v-if="loading">正在验证身份…</span>
            <span v-else>进入工作台 →</span>
          </button>
        </form>

        <div class="login-foot">
          <div class="foot-org">人工智能学院 · 教学科研与学生工作办公室</div>
          <div class="foot-tip">
            请遵守校园教学信息安全规范，妥善保管个人工作账号及权限密码。
          </div>
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

.login-brand-header {
  display: flex;
  align-items: center;
  gap: 14px;
  position: relative;
  z-index: 1;
}
.brand-school-logo {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  object-fit: cover;
  background: #ffffff;
  padding: 1px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25);
  flex-shrink: 0;
}
.brand-text .college-title {
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: var(--paper);
  line-height: 1.3;
}
.brand-text .college-sub {
  font-size: 10px;
  letter-spacing: 0.12em;
  color: var(--paper-deep);
  opacity: 0.65;
  margin-top: 2px;
}

.login-hero {
  position: relative;
  z-index: 1;
}
.term-badge {
  font-size: 12px;
  color: var(--accent-soft);
  letter-spacing: 0.08em;
  margin-bottom: 24px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.term-badge .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  display: inline-block;
}
.login-hero h1 {
  font-size: clamp(34px, 3.8vw, 50px);
  font-weight: 700;
  line-height: 1.25;
  letter-spacing: 0.02em;
  margin-bottom: 24px;
}
.login-hero p {
  font-size: 15px;
  line-height: 1.9;
  opacity: 0.65;
  max-width: 420px;
  font-weight: 300;
}

.login-meta {
  display: flex;
  gap: 48px;
  font-size: 12px;
  opacity: 0.65;
  position: relative;
  z-index: 1;
}
.login-meta span { display: block; }
.login-meta .num {
  font-size: 22px;
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
  background: var(--paper);
}
.login-form {
  width: 100%;
  max-width: 400px;
}

.form-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 28px;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--line);
}
.form-school-logo {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  object-fit: cover;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  flex-shrink: 0;
}
.form-header-text .school-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--ink);
  line-height: 1.25;
}
.form-header-text .platform-name {
  font-size: 10px;
  color: var(--ink-mute);
  letter-spacing: 0.06em;
  margin-top: 2px;
}

.form-welcome {
  margin-bottom: 32px;
}
.form-welcome h2 {
  font-size: 26px;
  font-weight: 600;
  color: var(--ink);
  line-height: 1.25;
}
.form-subtitle {
  font-size: 13px;
  color: var(--ink-soft);
  margin-top: 6px;
  line-height: 1.5;
}

.login-error {
  padding: 12px 16px;
  margin-bottom: 24px;
  background: var(--accent-soft);
  border-left: 2px solid var(--accent);
  font-size: 12px;
  color: var(--accent);
  font-weight: 500;
}

.field {
  margin-bottom: 24px;
}
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
.field input:focus {
  border-bottom-color: var(--ink);
}
.field input::placeholder {
  color: var(--ink-mute);
  font-weight: 300;
}

.login-submit {
  width: 100%;
  padding: 14px;
  justify-content: center;
  margin-top: 8px;
  font-size: 14px;
}

.login-foot {
  margin-top: 36px;
  padding-top: 20px;
  border-top: 1px solid var(--line);
  font-size: 11px;
  color: var(--ink-mute);
  line-height: 1.7;
}
.foot-org {
  font-weight: 600;
  color: var(--ink-soft);
  margin-bottom: 4px;
}
.foot-tip {
  color: var(--ink-mute);
  font-size: 11px;
}

@media (max-width: 900px) {
  .login-wrap {
    grid-template-columns: 1fr;
  }
  .login-left {
    display: none;
  }
  .login-right {
    padding: 36px 20px;
  }
  .login-form {
    max-width: 100%;
  }
}
</style>
