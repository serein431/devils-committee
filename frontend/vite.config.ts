import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { viteSingleFile } from 'vite-plugin-singlefile'

// 后端 GET / 只 read_text 单个 web/index.html,不 serve /assets/*,
// 所以 build 用 singlefile 把 JS/CSS 全内联进一个 HTML,产物落回 ../web/index.html。
// dev 下 proxy /a2a、/healthz 到 8080,解决跨域并逐块转发 SSE。
export default defineConfig({
  base: './',
  plugins: [react(), viteSingleFile()],
  server: {
    proxy: {
      '/a2a': { target: 'http://localhost:8080', changeOrigin: true },
      '/healthz': { target: 'http://localhost:8080', changeOrigin: true },
    },
  },
  build: {
    outDir: '../web',
    emptyOutDir: false, // 保住 web/ 里的备份与其它静态资源
  },
})
