<template>
  <div class="login-container">
    <!-- 背景光效装饰 -->
    <div class="glow-bg">
      <div class="glow-circle blue"></div>
      <div class="glow-circle purple"></div>
    </div>

    <!-- 登录注册卡片 -->
    <div class="auth-card">
      <div class="auth-header">
        <div class="logo">
          <span class="logo-text">AgentFlow</span>
        </div>
        <h2 class="auth-title">{{ isRegister ? '创建账号' : '登录您的账号' }}</h2>
        <p class="auth-subtitle">{{ isRegister ? '注册后自动开通独立工作区' : '进入您的工作流画布' }}</p>
      </div>

      <div class="auth-body">
        <el-form
          v-if="!isRegister"
          :model="loginForm"
          :rules="loginRules"
          ref="loginFormRef"
          label-position="top"
          @submit.prevent="handleLogin"
        >
          <el-form-item label="邮箱" prop="email">
            <el-input
              v-model="loginForm.email"
              placeholder="请输入邮箱"
              clearable
            >
              <template #prefix>
                <el-icon><User /></el-icon>
              </template>
            </el-input>
          </el-form-item>

          <el-form-item label="密码" prop="password">
            <el-input
              v-model="loginForm.password"
              type="password"
              placeholder="请输入密码"
              show-password
              clearable
            >
              <template #prefix>
                <el-icon><Lock /></el-icon>
              </template>
            </el-input>
          </el-form-item>

          <el-form-item class="form-actions">
            <el-button type="primary" :loading="loading" class="submit-btn" native-type="submit">
              立即登录
            </el-button>
          </el-form-item>
        </el-form>

        <el-form
          v-else
          ref="registerFormRef"
          :model="registerForm"
          :rules="registerRules"
          label-position="top"
          @submit.prevent="handleRegister"
        >
          <el-form-item label="昵称" prop="name">
            <el-input v-model="registerForm.name" placeholder="请输入昵称" clearable>
              <template #prefix><el-icon><EditPen /></el-icon></template>
            </el-input>
          </el-form-item>
          <el-form-item label="邮箱" prop="email">
            <el-input v-model="registerForm.email" placeholder="请输入邮箱" clearable>
              <template #prefix><el-icon><User /></el-icon></template>
            </el-input>
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input v-model="registerForm.password" type="password" placeholder="至少 8 位并包含字母和数字" show-password>
              <template #prefix><el-icon><Lock /></el-icon></template>
            </el-input>
          </el-form-item>
          <el-form-item label="确认密码" prop="passwordConfirm">
            <el-input v-model="registerForm.passwordConfirm" type="password" placeholder="请再次输入密码" show-password>
              <template #prefix><el-icon><Lock /></el-icon></template>
            </el-input>
          </el-form-item>
          <el-form-item class="form-actions">
            <el-button type="primary" :loading="loading" class="submit-btn" native-type="submit">
              创建账号
            </el-button>
          </el-form-item>
        </el-form>
      </div>

      <div class="auth-footer">
        <span class="footer-text">{{ isRegister ? '已有账号？' : '还没有账号？' }}</span>
        <el-button link type="primary" class="toggle-btn" @click="toggleMode">
          {{ isRegister ? '返回登录' : '立即注册' }}
        </el-button>
      </div>
    </div>


  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock, EditPen } from '@element-plus/icons-vue'
import { loginWithDify, registerWithDify } from '../../../shared/auth/difyAuth.js'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const isRegister = ref(false)

const loginFormRef = ref(null)
const registerFormRef = ref(null)

// 登录表单
const loginForm = reactive({
  email: '',
  password: ''
})

const loginRules = {
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '请输入正确的邮箱格式', trigger: 'blur' },
  ],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

const registerForm = reactive({
  name: '',
  email: '',
  password: '',
  passwordConfirm: '',
})

const registerRules = {
  name: [{ required: true, message: '请输入昵称', trigger: 'blur' }],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '请输入正确的邮箱格式', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 8, message: '密码至少需要 8 位', trigger: 'blur' },
  ],
  passwordConfirm: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => {
        if (value !== registerForm.password)
          callback(new Error('两次输入的密码不一致'))
        else
          callback()
      },
      trigger: 'blur',
    },
  ],
}

function toggleMode() {
  isRegister.value = !isRegister.value
  loginFormRef.value?.resetFields()
  registerFormRef.value?.resetFields()
}

// 登录提交
const handleLogin = async () => {
  if (!loginFormRef.value) return
  await loginFormRef.value.validate(async (valid) => {
    if (valid) {
      loading.value = true
      try {
        const res = await loginWithDify(loginForm.email, loginForm.password)
        if (res.result === 'success') {
          ElMessage.success('登录成功')
          // Wait a tick so Set-Cookie (csrf_token) is visible to document.cookie
          // before the route guard calls /account/profile.
          await Promise.resolve()
          const redirect = route.query.redirect || '/'
          router.push(redirect)
        } else {
          ElMessage.error(res.message || res.data || '登录失败')
        }
      } catch (error) {
        console.error(error)
      } finally {
        loading.value = false
      }
    }
  })
}

const handleRegister = async () => {
  if (!registerFormRef.value) return
  await registerFormRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      const response = await registerWithDify(registerForm)
      if (response.result === 'success') {
        ElMessage.success('注册成功')
        await Promise.resolve()
        router.push('/')
      }
    } catch (error) {
      console.error(error)
    } finally {
      loading.value = false
    }
  })
}

</script>

<style scoped>
.login-container {
  display: flex;
  justify-content: center;
  align-items: center;
  width: 100vw;
  height: 100vh;
  background-color: #f3f4f6;
  position: relative;
  overflow: hidden;
  font-family: var(--font-sans);
}

/* 渐变发光背景 - 轻量化处理 */
.glow-bg {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 1;
}

.glow-circle {
  position: absolute;
  width: 600px;
  height: 600px;
  border-radius: 50%;
  filter: blur(140px);
  opacity: 0.12;
}

.glow-circle.blue {
  background: radial-gradient(circle, #3b82f6 0%, transparent 70%);
  top: -15%;
  left: 15%;
}

.glow-circle.purple {
  background: radial-gradient(circle, #8b5cf6 0%, transparent 70%);
  bottom: -15%;
  right: 15%;
}

/* 登录卡片 - 清爽白色背景与立体阴影 */
.auth-card {
  position: relative;
  z-index: 10;
  width: 440px;
  padding: 40px;
  background: #ffffff;
  border: 1px solid #eaecf0;
  border-radius: 16px;
  box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.05), 0 8px 10px -6px rgba(0, 0, 0, 0.05);
  transition: all 0.3s ease;
}

.auth-card:hover {
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.07), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
}

.auth-header {
  text-align: center;
  margin-bottom: 30px;
}

.logo {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin-bottom: 20px;
}

.logo-text {
  font-size: 24px;
  font-weight: 800;
  letter-spacing: -0.5px;
  background: linear-gradient(135deg, #155ee9 0%, #1251c7 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.auth-title {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.auth-subtitle {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.4;
}

/* 表单输入框样式微调 - 匹配 Dify 输入框风格 */
:deep(.el-form-item__label) {
  color: var(--text-secondary) !important;
  font-weight: 500;
  font-size: 13px;
  margin-bottom: 6px !important;
}

:deep(.el-input__wrapper) {
  padding: 10px 14px !important;
  background-color: #ffffff !important;
  border: 1px solid #d0d5dd !important;
  box-shadow: none !important;
  border-radius: 8px !important;
}

:deep(.el-input__wrapper:hover) {
  border-color: #98a2b3 !important;
}

:deep(.el-input__wrapper.is-focus) {
  border-color: var(--color-primary) !important;
  box-shadow: 0 0 0 4px rgba(21, 94, 239, 0.1) !important;
}

:deep(.el-input__inner) {
  color: var(--text-primary) !important;
}

:deep(.el-input__prefix-icon) {
  color: var(--text-muted) !important;
}

.form-actions {
  margin-top: 30px;
  margin-bottom: 0;
}

.submit-btn {
  width: 100%;
  height: 44px;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.5px;
  background: var(--color-primary) !important;
  color: #ffffff !important;
  border: none;
  border-radius: 8px;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.05);
}

.submit-btn:hover {
  background: var(--color-primary-hover) !important;
  box-shadow: 0 1px 3px rgba(16, 24, 40, 0.1);
}

.auth-footer {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 8px;
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid #eaecf0;
}

.footer-text {
  font-size: 13px;
  color: var(--text-muted);
}

.toggle-btn {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-primary) !important;
}

.toggle-btn:hover {
  color: var(--color-primary-hover) !important;
}


</style>
