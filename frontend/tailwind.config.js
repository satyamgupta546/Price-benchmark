/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        blinkit: '#F8C723',
        jiomart: '#0078AD',
        flipkart: '#2874F0',
        zepto: '#8B22CF',
        instamart: '#FC8019',
      },
    },
  },
  plugins: [],
}
