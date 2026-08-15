import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../grid-agent/src/grid_agent/trajectory/static',
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      output: {
        entryFileNames: 'assets/app.js',
        chunkFileNames: 'assets/chunk-[name]-[hash].js',
        assetFileNames: (asset) =>
          asset.name?.endsWith('.css') ? 'assets/app.css' : 'assets/[name]-[hash][extname]',
      },
    },
  },
});
