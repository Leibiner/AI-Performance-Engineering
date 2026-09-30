import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

// history 模式：依赖后端（以及 Vite 开发服务器）在找不到文件时回退到 index.html。
const routes: RouteRecordRaw[] = [
  { path: '/', component: () => import('./views/OverviewPage.vue'), meta: { title: '概览', menu: '/' } },
  {
    path: '/executors',
    component: () => import('./views/ExecutorsPage.vue'),
    meta: { title: '执行机', menu: '/executors' },
  },
  {
    path: '/environments',
    component: () => import('./views/EnvironmentsPage.vue'),
    meta: { title: '被测环境', menu: '/environments' },
  },
  { path: '/apis', component: () => import('./views/ApisPage.vue'), meta: { title: '接口', menu: '/apis' } },
  { path: '/flows', component: () => import('./views/FlowsPage.vue'), meta: { title: '业务流程', menu: '/flows' } },
  {
    path: '/profiles',
    component: () => import('./views/ProfilesPage.vue'),
    meta: { title: '负载配置', menu: '/profiles' },
  },
  { path: '/tests', component: () => import('./views/TestsPage.vue'), meta: { title: '测试', menu: '/tests' } },
  { path: '/runs', component: () => import('./views/RunsPage.vue'), meta: { title: '运行', menu: '/runs' } },
  {
    path: '/runs/:runId',
    component: () => import('./views/RunDetailPage.vue'),
    props: true,
    meta: { title: '运行详情', menu: '/runs' },
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.afterEach((to) => {
  const title = typeof to.meta.title === 'string' ? to.meta.title : ''
  document.title = title ? `${title} · 性能测试控制台` : '性能测试控制台'
})
