import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  root: 'renderer',
  plugins: [react()],
  build: {
    target: 'chrome136',
  },
});
