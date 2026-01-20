const express = require('express');
const path = require('path');
const https = require('https');
const fs = require('fs');

const app = express();
const PORT = process.env.PORT || 3000;
const HTTPS_PORT = process.env.HTTPS_PORT || 3443;

// Serve static files from public directory
app.use(express.static(path.join(__dirname, 'public')));

// Routes
app.get('/', (req, res) => {
    res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

app.get('/contact', (req, res) => {
    res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

app.get('/projects', (req, res) => {
    res.sendFile(path.join(__dirname, 'public', 'projects.html'));
});

app.get('/support', (req, res) => {
    res.sendFile(path.join(__dirname, 'public', 'support.html'));
});

// Handle form submissions
app.post('/contact', express.json(), (req, res) => {
    // Simulate form processing
    console.log('Contact form submitted:', req.body);
    res.json({ success: true, message: 'Form submitted successfully!' });
});

// Start HTTP server
app.listen(PORT, () => {
    console.log(`HTTP Server running on http://localhost:${PORT}`);
    console.log(`Available routes:`);
    console.log(`  - http://localhost:${PORT}/ (Contact page)`);
    console.log(`  - http://localhost:${PORT}/contact (Contact page)`);
    console.log(`  - http://localhost:${PORT}/projects (Projects page)`);
    console.log(`  - http://localhost:${PORT}/support (Support page)`);
});

// HTTPS Configuration - with error handling
let httpsServer = null;
try {
    const httpsOptions = {
        key: fs.readFileSync(path.join(__dirname, '192.168.0.49.key')),
        cert: fs.readFileSync(path.join(__dirname, '192.168.0.49.pem'))
    };

    // Start HTTPS server
    httpsServer = https.createServer(httpsOptions, app).listen(HTTPS_PORT, () => {
        console.log(`HTTPS Server running on https://localhost:${HTTPS_PORT}`);
        console.log(`Available routes:`);
        console.log(`  - https://localhost:${HTTPS_PORT}/ (Contact page)`);
        console.log(`  - https://localhost:${HTTPS_PORT}/contact (Contact page)`);
        console.log(`  - https://localhost:${HTTPS_PORT}/projects (Projects page)`);
        console.log(`  - https://localhost:${HTTPS_PORT}/support (Support page)`);
    });
} catch (error) {
    console.log(`HTTPS server not started due to certificate issues: ${error.message}`);
    console.log(`Running in HTTP-only mode.`);
}

module.exports = app;