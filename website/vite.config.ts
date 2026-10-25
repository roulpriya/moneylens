import { defineConfig } from 'vite';
import tailwindcss from '@tailwindcss/vite';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  base: './',
  plugins: [tailwindcss()],
  server: {
    fs: { allow: [fileURLToPath(new URL('..', import.meta.url))] },
  },
  build: {
    rollupOptions: {
      input: {
        index: fileURLToPath(new URL('./index.html', import.meta.url)),
        policy: fileURLToPath(new URL('./policy.html', import.meta.url)),
        terms: fileURLToPath(new URL('./terms.html', import.meta.url)),
      },
    },
  },
});
