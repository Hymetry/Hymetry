# Run from script dir so npm finds package.json and input.css
cd ./frontend/tailwind/

# Production build (minified) - outputs to /static/css/output.css
npm run build:prod

# Development build (with watch mode) - outputs to /static/css/output.css  
# npm run build