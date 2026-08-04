const http = require('http');
const fs = require('fs');
const path = require('path');
const { URL } = require('url');

const mimeTypes = {
    '.html': 'text/html',
    '.js': 'text/javascript',
    '.css': 'text/css',
    '.json': 'application/json',
    '.png': 'image/png',
    '.jpg': 'image/jpg',
    '.gif': 'image/gif',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2'
};

const API_HOST = process.env.API_HOST || 'geo-backend';
const API_PORT = process.env.API_PORT || 5000;

const server = http.createServer((req, res) => {
    if (req.url.startsWith('/api/')) {
        proxyApiRequest(req, res);
        return;
    }

    // 处理URL，去掉查询参数
    let urlPath = req.url.split('?')[0];
    let filePath = '.' + urlPath;
    if (filePath === './') {
        filePath = './index.html';
    }

    const extname = String(path.extname(filePath)).toLowerCase();
    const contentType = mimeTypes[extname] || 'application/octet-stream';

    fs.readFile(filePath, (error, content) => {
        if (error) {
            if (error.code === 'ENOENT') {
                res.writeHead(404, { 'Content-Type': 'text/html; charset=utf-8' });
                res.end(`
                    <html>
                    <head><title>404 - 页面未找到</title></head>
                    <body style="font-family: Arial; padding: 2rem; text-align: center;">
                        <h1>404 - 页面未找到</h1>
                        <p>请求的页面: ${req.url}</p>
                        <p>可用页面：</p>
                        <ul style="list-style: none; padding: 0;">
                            <li><a href="/">首页</a></li>
                            <li><a href="/geo_demo.html">GEO优化专家（新）</a></li>
                            <li><a href="/geo_optimizer.html">GEO优化方案</a></li>
                            <li><a href="/website_diagnose.html">网站诊断</a></li>
                        </ul>
                    </body>
                    </html>
                `, 'utf-8');
            } else {
                res.writeHead(500);
                res.end('Server Error: ' + error.code);
            }
        } else {
            res.writeHead(200, { 'Content-Type': contentType });
            res.end(content, 'utf-8');
        }
    });
});

function proxyApiRequest(req, res) {
    const url = new URL(req.url, `http://${API_HOST}:${API_PORT}`);
    
    const options = {
        hostname: API_HOST,
        port: API_PORT,
        path: url.pathname + url.search,
        method: req.method,
        headers: {
            ...req.headers,
            host: `${API_HOST}:${API_PORT}`
        }
    };

    const proxyReq = http.request(options, (proxyRes) => {
        res.writeHead(proxyRes.statusCode, proxyRes.headers);
        proxyRes.pipe(res);
    });

    proxyReq.on('error', (e) => {
        console.error('API Proxy Error:', e);
        res.writeHead(503, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Service unavailable' }));
    });

    req.pipe(proxyReq);
}

const PORT = process.env.PORT || 8080;
server.listen(PORT, () => {
    console.log('');
    console.log('🚀 GEO优化系统前端服务启动成功！');
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log(`📍 访问地址: http://localhost:${PORT}`);
    console.log(`🔌 API 代理: http://${API_HOST}:${API_PORT}`);
    console.log('');
    console.log('📄 可用页面:');
    console.log('   • /                  - 首页');
    console.log('   • /geo_demo.html     - GEO优化专家（新）');
    console.log('   • /geo_optimizer.html - GEO优化方案');
    console.log('   • /website_diagnose.html - 网站诊断');
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
});
