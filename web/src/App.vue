<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  Connection,
  Cpu,
  DataLine,
  Files,
  Link,
  List,
  Monitor,
  Odometer,
  Tickets,
} from '@element-plus/icons-vue'
import { systemApi, type SystemInfo } from './api'

const route = useRoute()
const activeMenu = computed(() => (typeof route.meta.menu === 'string' ? route.meta.menu : route.path))

const menu = [
  { index: '/', label: '概览', icon: Odometer },
  // 执行机和被测环境相邻：一个是发起压测的机器，一个是被压的系统
  { index: '/executors', label: '执行机', icon: Cpu },
  { index: '/environments', label: '被测环境', icon: Monitor },
  { index: '/apis', label: '接口', icon: Link },
  { index: '/flows', label: '业务流程', icon: Connection },
  { index: '/data', label: '测试数据', icon: Files },
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
    <el-main class="layout-main">
      <!-- 以完整路径为 key：从一个运行跳到另一个运行时重新创建页面 -->
      <!-- 按路径而不是完整地址：查询参数变了（如接口页的 ?id=）不重建页面 -->
      <router-view :key="route.path" />
    </el-main>
  </el-container>
</template>
