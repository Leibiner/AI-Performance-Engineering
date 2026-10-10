import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 后端把 web/dist 托管在同一个端口，接口统一走相对路径 /api。
// 开发时由 Vite 把 /api 代理到本机后端。
export default defineConfig({
  plugins: [vue()],
  // 前端用 history 路由，资源必须用绝对路径引用，否则在 /runs/xxx 这类地址下刷新会找不到文件
  base: '/',
  server: {
    host: '0.0.0.0',
    port: 5180,
    proxy: {
      // 用正则：'/api' 是前缀匹配，会把页面路由 /apis 也转给后端
      '^/api/': 'http://localhost:8088',
    },
  },
  build: {
    // Element Plus 全量引入后主包约 1 MB，属于预期，不需要警告。
    chunkSizeWarningLimit: 1500,
  },
})
