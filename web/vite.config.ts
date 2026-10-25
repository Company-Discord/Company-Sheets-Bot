import { defineConfig } from 'vite';

export default defineConfig({
  server: {proxy: {'/api': 'http://localhost:8000', '/auth': 'http://localhost:8000'}},
});
