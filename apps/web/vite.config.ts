import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

const API_TARGET = 'http://127.0.0.1:8000';

/** Group third-party code so the two route chunks stay small and the vendor chunks cache well. */
function vendorChunk(id: string): string | undefined {
  if (!id.includes('node_modules')) return undefined;
  if (
    /node_modules\/(react|react-dom|scheduler|react-router|react-router-dom|@remix-run)\//.test(id)
  ) {
    return 'react';
  }
  if (id.includes('@tanstack')) return 'query';
  if (/node_modules\/(@visx|d3-[a-z-]+|lodash|internmap|classnames|prop-types)\//.test(id)) {
    return 'viz';
  }
  return undefined;
}

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': API_TARGET,
      '/healthz': API_TARGET,
    },
  },
  build: {
    outDir: 'dist',
    rollupOptions: { output: { manualChunks: vendorChunk } },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
  },
});
