<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  Connection,
  Cpu,
  DataLine,
  Link,
  List,
  Monitor,
  Odometer,
  Tickets,
} from '@element-plus/icons-vue'
import { systemApi, type SystemInfo } from './api'
import { useDebugContext } from './composables/useDebugContext'
import EnvPicker from './components/debug/EnvPicker.vue'

const route = useRoute()
const activeMenu = computed(() => (typeof route.meta.menu === 'string' ? route.meta.menu : route.path))

// 页头右上角的"当前调试环境"：接口页的发送和业务流程的试跑都发往它；发起运行时默认选中它。
// 换页面时刷新一次列表，在被测环境页改过的名称、新建的环境马上生效。
const debugCtx = useDebugContext()
watch(
  () => route.path,
  () => {
    void debugCtx.loadEnvironments()
  },
)

const menu = [
  { index: '/', label: '概览', icon: Odometer },
  // 执行机和被测环境相邻：一个是发起压测的机器，一个是被压的系统
  { index: '/executors', label: '执行机', icon: Cpu },
  { index: '/environments', label: '被测环境', icon: Monitor },
  { index: '/apis', label: '接口', icon: Link },
  { index: '/flows', label: '业务流程', icon: Connection },
  { index: '/profiles', label: '负载配置', icon: DataLine },
  { index: '/tests', label: '测试', icon: Tickets },
  { index: '/runs', label: '运行', icon: List },
]

// 侧栏底部显示 k6 版本；有运行在进行时给出全局入口。后端不可用时静默。
const system = ref<SystemInfo | null>(null)
let timer: number | undefined

async function refreshSystem(): Promise<void> {
  try {
    system.value = await systemApi.get()
  } catch {
    system.value = null
  }
}

onMounted(() => {
  void refreshSystem()
  timer = window.setInterval(refreshSystem, 5000)
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <el-container class="layout">
    <el-aside class="layout-aside" width="200px">
      <div class="brand">
        <div class="brand-title">性能测试控制台</div>
        <div class="brand-sub">k6 · MVP</div>
      </div>
      <el-menu :default-active="activeMenu" router class="layout-menu">
        <el-menu-item v-for="item in menu" :key="item.index" :index="item.index">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </el-menu-item>
      </el-menu>
      <div class="aside-footer">
        <router-link v-if="system?.runningRunId" class="running-pill" :to="`/runs/${system.runningRunId}`">
          <span class="running-dot" />
          有运行正在进行
        </router-link>
        <div v-if="system" class="aside-meta">k6 {{ system.k6Version }}</div>
        <div v-else class="aside-meta aside-meta--warn">未连接到后端</div>
      </div>
    </el-aside>
    <el-container direction="vertical" class="layout-body">
      <header class="topbar">
        <div class="topbar-env">
          <span class="topbar-label" title="接口页的“发送”和业务流程的“试跑”都发往这里；发起运行时默认选中它，仍可在对话框里改">调试环境</span>
          <EnvPicker />
          <router-link class="topbar-link" to="/environments">管理</router-link>
        </div>
      </header>
      <el-main class="layout-main">
        <!-- 以完整路径为 key：从一个运行跳到另一个运行时重新创建页面 -->
        <router-view :key="route.fullPath" />
      </el-main>
    </el-container>
  </el-container>
</template>
