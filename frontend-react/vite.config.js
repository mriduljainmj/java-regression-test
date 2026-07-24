import react from "@vitejs/plugin-react";

export default {
  plugins: [react()],
  // Relative asset paths so the built dist/ works behind any static file server.
  base: "./"
};
