/**
 * GEO系统前端应用
 * 与后端API交互
 */

// API基础URL
const API_BASE_URL = 'http://122.51.51.177:5001/api';

// 全局状态
const state = {
    token: localStorage.getItem('access_token'),
    user: null,
    currentSection: 'home'
};

// ==================== 认证检查 ====================

// 检查用户是否已登录
function checkAuth() {
    const token = localStorage.getItem('access_token');
    if (!token) {
        window.location.href = 'login.html';
        return false;
    }
    return true;
}

// 获取当前用户信息
async function getCurrentUser() {
    try {
        const response = await fetch(`${API_BASE_URL}/auth/profile`, {
            headers: {
                'Authorization': `Bearer ${state.token}`
            }
        });
        const data = await response.json();
        if (data.success) {
            state.user = data.data;
            document.getElementById('currentUser').textContent = `👤 ${data.data.username}`;
        }
    } catch (error) {
        console.error('获取用户信息失败:', error);
    }
}

// 退出登录
function logout() {
    localStorage.removeItem('access_token');
    localStorage.removeItem('username');
    window.location.href = 'login.html';
}

// 页面加载时检查认证
if (!checkAuth()) {
    throw new Error('未登录');
}

// 页面加载完成后获取用户信息
document.addEventListener('DOMContentLoaded', () => {
    getCurrentUser();
    
    // 绑定退出按钮
    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', logout);
    }
});

// ==================== 工具函数 ====================

/**
 * API请求封装
 */
async function apiRequest(endpoint, options = {}) {
    const url = `${API_BASE_URL}${endpoint}`;
    
    const config = {
        headers: {
            'Content-Type': 'application/json',
            ...options.headers
        },
        ...options
    };
    
    // 添加认证token
    if (state.token) {
        config.headers['Authorization'] = `Bearer ${state.token}`;
    }
    
    try {
        const response = await fetch(url, config);
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.message || '请求失败');
        }
        
        return data;
    } catch (error) {
        console.error('API请求错误:', error);
        throw error;
    }
}

/**
 * 显示加载状态
 */
function showLoading(elementId, message = '加载中...') {
    const element = document.getElementById(elementId);
    if (element) {
        element.innerHTML = `<div class="loading"><div class="spinner"></div><p>${message}</p></div>`;
        element.style.display = 'block';
    }
}

/**
 * 隐藏加载状态
 */
function hideLoading(elementId) {
    const element = document.getElementById(elementId);
    if (element) {
        element.style.display = 'none';
    }
}

/**
 * 显示消息
 */
function showMessage(message, type = 'info') {
    const messageContainer = document.getElementById('messageContainer');
    if (!messageContainer) return;
    
    const messageEl = document.createElement('div');
    messageEl.className = `message message-${type}`;
    messageEl.textContent = message;
    
    messageContainer.appendChild(messageEl);
    
    setTimeout(() => {
        messageEl.remove();
    }, 3000);
}

/**
 * 切换页面部分
 */
function showSection(sectionId) {
    // 隐藏所有部分
    document.querySelectorAll('.section').forEach(section => {
        section.classList.remove('active');
    });
    
    // 显示指定部分
    const targetSection = document.getElementById(sectionId);
    if (targetSection) {
        targetSection.classList.add('active');
        state.currentSection = sectionId;
    }
    
    // 更新导航状态
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.remove('active');
        if (item.dataset.section === sectionId) {
            item.classList.add('active');
        }
    });
    
    // 滚动到顶部
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ==================== 认证相关 ====================

/**
 * 用户登录
 */
async function login(username, password) {
    try {
        const data = await apiRequest('/auth/login', {
            method: 'POST',
            body: JSON.stringify({ username, password })
        });
        
        if (data.success) {
            state.token = data.access_token;
            localStorage.setItem('geo_token', data.access_token);
            state.user = { username };
            showMessage('登录成功', 'success');
            return true;
        }
    } catch (error) {
        showMessage(error.message, 'error');
        return false;
    }
}

/**
 * 用户注册
 */
async function register(username, password) {
    try {
        const data = await apiRequest('/auth/register', {
            method: 'POST',
            body: JSON.stringify({ username, password })
        });
        
        if (data.success) {
            showMessage('注册成功，请登录', 'success');
            return true;
        }
    } catch (error) {
        showMessage(error.message, 'error');
        return false;
    }
}

/**
 * 用户登出
 */
function logout() {
    state.token = null;
    state.user = null;
    localStorage.removeItem('geo_token');
    showMessage('已登出', 'info');
    showSection('login');
}

// ==================== 内容生成 ====================

/**
 * 生成内容
 */
async function generateContent(formData) {
    showLoading('generateResult', '正在生成GEO优化内容...');
    
    try {
        const data = await apiRequest('/content/generate', {
            method: 'POST',
            body: JSON.stringify({
                title: formData.title,
                brand_info: {
                    name: formData.brandName,
                    industry: formData.industry,
                    expertise: formData.expertise.split('\n').filter(e => e.trim())
                },
                target_platform: formData.platform,
                word_count: parseInt(formData.wordCount)
            })
        });
        
        if (data.success) {
            displayGenerationResult(data.data);
            showMessage('内容生成成功', 'success');
        }
    } catch (error) {
        showMessage(error.message, 'error');
    } finally {
        hideLoading('generateResult');
    }
}

/**
 * 显示生成结果
 */
function displayGenerationResult(result) {
    const container = document.getElementById('generateResult');
    
    let outlineHtml = '<div class="outline-tree">';
    result.outline.forEach(item => {
        const indent = '  '.repeat(item.level - 1);
        outlineHtml += `<div class="outline-item level-${item.level}">${indent}${item.title}</div>`;
    });
    outlineHtml += '</div>';
    
    container.innerHTML = `
        <div class="result-header">
            <h4>📄 生成结果</h4>
            <div class="result-actions">
                <button class="btn btn-sm" onclick="downloadJSON('${encodeURIComponent(JSON.stringify(result))}', 'geo_outline.json')">下载JSON</button>
                <button class="btn btn-sm" onclick="copyToClipboard('${encodeURIComponent(result.prompt)}')">复制提示词</button>
            </div>
        </div>
        <div class="result-content">
            <h5>文章大纲</h5>
            ${outlineHtml}
        </div>
        <div class="result-prompt">
            <h5>提示词 (${result.prompt.length} 字符)</h5>
            <textarea readonly class="prompt-textarea">${result.prompt}</textarea>
        </div>
    `;
    container.style.display = 'block';
}

/**
 * 批量生成内容
 */
async function batchGenerate(topics, brandInfo) {
    showLoading('batchResult', '正在批量生成内容...');
    
    try {
        const data = await apiRequest('/content/batch-generate', {
            method: 'POST',
            body: JSON.stringify({
                topics: topics,
                brand_info: brandInfo
            })
        });
        
        if (data.success) {
            displayBatchResult(data.data);
            showMessage(`成功生成 ${data.data.total} 个内容大纲`, 'success');
        }
    } catch (error) {
        showMessage(error.message, 'error');
    } finally {
        hideLoading('batchResult');
    }
}

// ==================== 内容分析 ====================

/**
 * 分析内容
 */
async function analyzeContent(content) {
    showLoading('analyzeResult', '正在分析内容质量...');
    
    try {
        const data = await apiRequest('/content/analyze', {
            method: 'POST',
            body: JSON.stringify({ content })
        });
        
        if (data.success) {
            displayAnalysisResult(data.data);
            showMessage('分析完成', 'success');
        }
    } catch (error) {
        showMessage(error.message, 'error');
    } finally {
        hideLoading('analyzeResult');
    }
}

/**
 * 显示分析结果
 */
function displayAnalysisResult(result) {
    const container = document.getElementById('analyzeResult');
    
    const grade = result.overall_score >= 80 ? '优秀' : 
                  result.overall_score >= 60 ? '良好' : '需改进';
    const gradeClass = result.overall_score >= 80 ? 'excellent' : 
                       result.overall_score >= 60 ? 'good' : 'poor';
    
    container.innerHTML = `
        <div class="analysis-result">
            <div class="score-overview">
                <div class="score-circle ${gradeClass}">
                    <span class="score-value">${result.overall_score.toFixed(1)}</span>
                    <span class="score-label">${grade}</span>
                </div>
                <div class="score-details">
                    <div class="score-bar-item">
                        <span>结构得分</span>
                        <div class="progress-bar"><div class="progress-fill" style="width: ${result.structure_score}%"></div></div>
                        <span>${result.structure_score.toFixed(1)}</span>
                    </div>
                    <div class="score-bar-item">
                        <span>引用得分</span>
                        <div class="progress-bar"><div class="progress-fill" style="width: ${result.citation_score}%"></div></div>
                        <span>${result.citation_score.toFixed(1)}</span>
                    </div>
                    <div class="score-bar-item">
                        <span>可读性得分</span>
                        <div class="progress-bar"><div class="progress-fill" style="width: ${result.readability_score}%"></div></div>
                        <span>${result.readability_score.toFixed(1)}</span>
                    </div>
                    <div class="score-bar-item">
                        <span>权威性得分</span>
                        <div class="progress-bar"><div class="progress-fill" style="width: ${result.authority_score}%"></div></div>
                        <span>${result.authority_score.toFixed(1)}</span>
                    </div>
                </div>
            </div>
            
            ${result.issues.length > 0 ? `
                <div class="issues-section">
                    <h5>⚠️ 发现的问题</h5>
                    <ul>
                        ${result.issues.map(issue => `<li>${issue}</li>`).join('')}
                    </ul>
                </div>
            ` : ''}
            
            ${result.suggestions.length > 0 ? `
                <div class="suggestions-section">
                    <h5>💡 优化建议</h5>
                    <ul>
                        ${result.suggestions.map(s => `<li>${s}</li>`).join('')}
                    </ul>
                </div>
            ` : ''}
        </div>
    `;
    container.style.display = 'block';
}

// ==================== 内容优化 ====================

/**
 * 优化内容
 */
async function optimizeContent(content, level) {
    showLoading('optimizeResult', '正在优化内容...');
    
    try {
        const data = await apiRequest('/content/optimize', {
            method: 'POST',
            body: JSON.stringify({
                content,
                optimization_level: level
            })
        });
        
        if (data.success) {
            displayOptimizationResult(data.data);
            showMessage('优化完成', 'success');
        }
    } catch (error) {
        showMessage(error.message, 'error');
    } finally {
        hideLoading('optimizeResult');
    }
}

/**
 * 显示优化结果
 */
function displayOptimizationResult(result) {
    const container = document.getElementById('optimizeResult');
    const improvement = result.score_after - result.score_before;
    const improvementPercent = ((improvement / Math.max(result.score_before, 1)) * 100).toFixed(1);
    
    container.innerHTML = `
        <div class="optimization-result">
            <div class="optimization-stats">
                <div class="stat-item">
                    <span class="stat-label">优化前</span>
                    <span class="stat-value">${result.score_before.toFixed(1)}</span>
                </div>
                <div class="stat-arrow">→</div>
                <div class="stat-item">
                    <span class="stat-label">优化后</span>
                    <span class="stat-value highlight">${result.score_after.toFixed(1)}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">提升</span>
                    <span class="stat-value success">+${improvement.toFixed(1)} (+${improvementPercent}%)</span>
                </div>
            </div>
            
            ${result.improvements.length > 0 ? `
                <div class="improvements-list">
                    <h5>📝 改进内容</h5>
                    <ul>
                        ${result.improvements.map(i => `<li>${i}</li>`).join('')}
                    </ul>
                </div>
            ` : ''}
            
            <div class="optimized-content">
                <h5>优化后的内容</h5>
                <textarea readonly class="content-textarea">${result.optimized_content}</textarea>
                <button class="btn btn-sm" onclick="downloadText('${encodeURIComponent(result.optimized_content)}', 'optimized_content.md')">下载内容</button>
            </div>
        </div>
    `;
    container.style.display = 'block';
}

// ==================== 数据监测 ====================

/**
 * 记录指标
 */
async function recordMetrics(metrics) {
    try {
        const data = await apiRequest('/metrics/record', {
            method: 'POST',
            body: JSON.stringify(metrics)
        });
        
        if (data.success) {
            showMessage('指标记录成功', 'success');
            return true;
        }
    } catch (error) {
        showMessage(error.message, 'error');
        return false;
    }
}

/**
 * 获取指标报告
 */
async function getMetricsReport(type = 'monthly') {
    showLoading('metricsReport', '正在生成报告...');
    
    try {
        const data = await apiRequest(`/metrics/report?type=${type}`);
        
        if (data.success) {
            displayMetricsReport(data.data);
        }
    } catch (error) {
        showMessage(error.message, 'error');
    } finally {
        hideLoading('metricsReport');
    }
}

/**
 * 显示指标报告
 */
function displayMetricsReport(report) {
    const container = document.getElementById('metricsReport');
    
    container.innerHTML = `
        <div class="metrics-report">
            <div class="metrics-grid">
                <div class="metric-card-large">
                    <span class="metric-label">AI引用率</span>
                    <span class="metric-value">${report.basic_metrics.ai_citation_rate.current.toFixed(1)}</span>
                    <span class="metric-change ${report.basic_metrics.ai_citation_rate.change >= 0 ? 'positive' : 'negative'}">
                        ${report.basic_metrics.ai_citation_rate.change >= 0 ? '↑' : '↓'} ${Math.abs(report.basic_metrics.ai_citation_rate.change).toFixed(1)}
                    </span>
                </div>
                <div class="metric-card-large">
                    <span class="metric-label">品牌提及率</span>
                    <span class="metric-value">${report.basic_metrics.brand_mention_rate.current.toFixed(1)}</span>
                    <span class="metric-change ${report.basic_metrics.brand_mention_rate.change >= 0 ? 'positive' : 'negative'}">
                        ${report.basic_metrics.brand_mention_rate.change >= 0 ? '↑' : '↓'} ${Math.abs(report.basic_metrics.brand_mention_rate.change).toFixed(1)}
                    </span>
                </div>
                <div class="metric-card-large">
                    <span class="metric-label">答案空间覆盖</span>
                    <span class="metric-value">${(report.basic_metrics.answer_space_coverage.current * 100).toFixed(1)}%</span>
                    <span class="metric-change ${report.basic_metrics.answer_space_coverage.change >= 0 ? 'positive' : 'negative'}">
                        ${report.basic_metrics.answer_space_coverage.change >= 0 ? '↑' : '↓'} ${Math.abs(report.basic_metrics.answer_space_coverage.change * 100).toFixed(1)}%
                    </span>
                </div>
                <div class="metric-card-large">
                    <span class="metric-label">综合可见性</span>
                    <span class="metric-value">${report.basic_metrics.visibility_score.current.toFixed(1)}</span>
                    <span class="metric-change ${report.basic_metrics.visibility_score.change >= 0 ? 'positive' : 'negative'}">
                        ${report.basic_metrics.visibility_score.change >= 0 ? '↑' : '↓'} ${Math.abs(report.basic_metrics.visibility_score.change).toFixed(1)}
                    </span>
                </div>
            </div>
            
            ${report.recommendations.length > 0 ? `
                <div class="recommendations">
                    <h5>💡 优化建议</h5>
                    <div class="recommendation-list">
                        ${report.recommendations.map(rec => `
                            <div class="recommendation-item priority-${rec.priority}">
                                <span class="priority-badge">${rec.priority === 'high' ? '高' : rec.priority === 'medium' ? '中' : '低'}</span>
                                <span class="recommendation-text">${rec.suggestion}</span>
                            </div>
                        `).join('')}
                    </div>
                </div>
            ` : ''}
        </div>
    `;
    container.style.display = 'block';
}

// ==================== ROI计算 ====================

/**
 * 计算ROI
 */
async function calculateROI(params) {
    showLoading('roiResult', '正在计算ROI...');
    
    try {
        const data = await apiRequest('/roi/calculate', {
            method: 'POST',
            body: JSON.stringify(params)
        });
        
        if (data.success) {
            displayROIResult(data.data);
        }
    } catch (error) {
        showMessage(error.message, 'error');
    } finally {
        hideLoading('roiResult');
    }
}

/**
 * 显示ROI结果
 */
function displayROIResult(result) {
    const container = document.getElementById('roiResult');
    
    const evaluation = result.roi_percentage >= 200 ? { text: '🌟 优秀的投资回报！建议立即实施。', class: 'excellent' } :
                       result.roi_percentage >= 100 ? { text: '✅ 良好的投资回报，值得实施。', class: 'good' } :
                       result.roi_percentage >= 50 ? { text: '⚠️ 中等回报，建议优化参数后实施。', class: 'warning' } :
                       { text: '❌ 回报较低，建议重新评估策略。', class: 'poor' };
    
    container.innerHTML = `
        <div class="roi-result">
            <div class="roi-stats-grid">
                <div class="roi-stat">
                    <span class="stat-label">总投资</span>
                    <span class="stat-value">¥${result.total_investment.toLocaleString()}</span>
                </div>
                <div class="roi-stat">
                    <span class="stat-label">预期收益</span>
                    <span class="stat-value">¥${result.revenue.toLocaleString()}</span>
                </div>
                <div class="roi-stat">
                    <span class="stat-label">净收益</span>
                    <span class="stat-value">¥${result.net_profit.toLocaleString()}</span>
                </div>
                <div class="roi-stat">
                    <span class="stat-label">ROI</span>
                    <span class="stat-value highlight">${result.roi_percentage.toFixed(1)}%</span>
                </div>
                <div class="roi-stat">
                    <span class="stat-label">回收期</span>
                    <span class="stat-value">${result.payback_period_months.toFixed(1)}个月</span>
                </div>
                <div class="roi-stat">
                    <span class="stat-label">新客户</span>
                    <span class="stat-value">${result.new_customers.toLocaleString()}</span>
                </div>
            </div>
            
            <div class="roi-evaluation ${evaluation.class}">
                ${evaluation.text}
            </div>
        </div>
    `;
    container.style.display = 'block';
}

// ==================== 信源建设 ====================

/**
 * 获取信源金字塔
 */
async function getAuthorityPyramid() {
    try {
        const data = await apiRequest('/authority/pyramid');
        
        if (data.success) {
            displayAuthorityPyramid(data.data);
        }
    } catch (error) {
        showMessage(error.message, 'error');
    }
}

/**
 * 显示信源金字塔
 */
function displayAuthorityPyramid(pyramid) {
    const container = document.getElementById('authorityPyramid');
    
    container.innerHTML = `
        <div class="pyramid-visual">
            ${Object.entries(pyramid.levels).reverse().map(([level, info]) => `
                <div class="pyramid-level level-${level}">
                    <div class="level-content">
                        <span class="level-name">${info.name}</span>
                        <span class="level-weight">权重 ${(info.weight * 100).toFixed(0)}%</span>
                    </div>
                </div>
            `).join('')}
        </div>
    `;
}

// ==================== 工具函数 ====================

/**
 * 下载JSON文件
 */
function downloadJSON(data, filename) {
    const decodedData = decodeURIComponent(data);
    const blob = new Blob([decodedData], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

/**
 * 下载文本文件
 */
function downloadText(content, filename) {
    const decodedContent = decodeURIComponent(content);
    const blob = new Blob([decodedContent], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

/**
 * 复制到剪贴板
 */
async function copyToClipboard(text) {
    try {
        const decodedText = decodeURIComponent(text);
        await navigator.clipboard.writeText(decodedText);
        showMessage('已复制到剪贴板', 'success');
    } catch (err) {
        showMessage('复制失败', 'error');
    }
}

// ==================== 初始化 ====================

document.addEventListener('DOMContentLoaded', function() {
    // 绑定导航事件
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            showSection(item.dataset.section);
        });
    });
    
    // 绑定表单提交事件
    const generateForm = document.getElementById('generateForm');
    if (generateForm) {
        generateForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const formData = {
                title: document.getElementById('title').value,
                brandName: document.getElementById('brandName').value,
                industry: document.getElementById('industry').value,
                expertise: document.getElementById('expertise').value,
                platform: document.getElementById('platform').value,
                wordCount: document.getElementById('wordCount').value
            };
            generateContent(formData);
        });
    }
    
    const analyzeForm = document.getElementById('analyzeForm');
    if (analyzeForm) {
        analyzeForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const content = document.getElementById('analyzeContent').value;
            analyzeContent(content);
        });
    }
    
    const optimizeForm = document.getElementById('optimizeForm');
    if (optimizeForm) {
        optimizeForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const content = document.getElementById('optimizeContent').value;
            const level = document.getElementById('optimizeLevel').value;
            optimizeContent(content, level);
        });
    }
    
    const metricsForm = document.getElementById('metricsForm');
    if (metricsForm) {
        metricsForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const metrics = {
                ai_citation_count: parseInt(document.getElementById('citationCount').value) || 0,
                brand_mention_count: parseInt(document.getElementById('mentionCount').value) || 0,
                answer_space_coverage: parseFloat(document.getElementById('coverage').value) || 0,
                source_diversity_score: parseFloat(document.getElementById('diversity').value) || 0,
                content_quality_score: parseFloat(document.getElementById('quality').value) || 0,
                citations_by_platform: {},
                mentions_by_source: {},
                top_queries: []
            };
            recordMetrics(metrics);
        });
    }
    
    const roiForm = document.getElementById('roiForm');
    if (roiForm) {
        roiForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const params = {
                content_investment: parseFloat(document.getElementById('contentInvestment').value) || 0,
                technology_investment: parseFloat(document.getElementById('techInvestment').value) || 0,
                personnel_investment: parseFloat(document.getElementById('personnelInvestment').value) || 0,
                ai_citation_increase: parseFloat(document.getElementById('citationIncrease').value) || 0,
                conversion_rate: parseFloat(document.getElementById('conversionRate').value) || 0,
                avg_customer_value: parseFloat(document.getElementById('customerValue').value) || 0
            };
            calculateROI(params);
        });
    }
    
    // 加载信源金字塔
    getAuthorityPyramid();
    
    // 显示首页
    showSection('home');
});

// ==================== GEO优化专家功能 ====================

/**
 * 网站诊断
 */
async function runGeoDiagnose() {
    console.log('runGeoDiagnose called');
    
    const diagnoseBtn = document.querySelector('.action-buttons .btn-primary:first-of-type');
    const planBtn = document.querySelector('.action-buttons .btn-primary:last-of-type');
    
    const brand = document.getElementById('geoBrand');
    const domain = document.getElementById('geoDomain');
    const geoLoading = document.getElementById('geoLoading');
    const geoDiagnoseResult = document.getElementById('geoDiagnoseResult');
    const geoPlanResult = document.getElementById('geoPlanResult');
    const diagnoseContent = document.getElementById('diagnoseContent');
    
    if (!brand || !domain) {
        showMessage('找不到表单元素', 'error');
        return;
    }
    
    const brandValue = brand.value.trim();
    const domainValue = domain.value.trim();
    
    if (!brandValue || !domainValue) {
        showMessage('请填写品牌名称和网站域名', 'error');
        return;
    }
    
    if (diagnoseBtn) diagnoseBtn.disabled = true;
    if (planBtn) planBtn.disabled = true;
    
    if (geoLoading) geoLoading.style.display = 'flex';
    if (geoDiagnoseResult) geoDiagnoseResult.style.display = 'none';
    if (geoPlanResult) geoPlanResult.style.display = 'none';

    try {
        const result = await apiRequest('/website/diagnose', {
            method: 'POST',
            body: JSON.stringify({ url: domainValue, brand_name: brandValue })
        });
        
        if (result.success && result.data) {
            displayDiagnoseResult(result.data);
            showMessage('网站诊断完成', 'success');
        } else {
            showMessage(result.message || '诊断失败', 'error');
        }
    } catch (error) {
        console.error('诊断失败:', error);
        showMessage('诊断请求失败: ' + error.message, 'error');
    } finally {
        if (diagnoseBtn) diagnoseBtn.disabled = false;
        if (planBtn) planBtn.disabled = false;
        if (geoLoading) geoLoading.style.display = 'none';
        if (geoDiagnoseResult) geoDiagnoseResult.style.display = 'block';
    }
}

/**
 * 生成优化方案
 */
async function generateGeoPlan() {
    console.log('generateGeoPlan called');
    
    const diagnoseBtn = document.querySelector('.action-buttons .btn-primary:first-of-type');
    const planBtn = document.querySelector('.action-buttons .btn-primary:last-of-type');
    
    const brand = document.getElementById('geoBrand').value;
    const domain = document.getElementById('geoDomain').value;
    const industry = document.getElementById('geoIndustry').value;
    const location = document.getElementById('geoLocation').value;
    
    if (!brand) {
        showMessage('请填写品牌名称', 'error');
        return;
    }
    
    const geoLoading = document.getElementById('geoLoading');
    const geoDiagnoseResult = document.getElementById('geoDiagnoseResult');
    const geoPlanResult = document.getElementById('geoPlanResult');
    
    if (diagnoseBtn) diagnoseBtn.disabled = true;
    if (planBtn) planBtn.disabled = true;
    
    if (geoLoading) geoLoading.style.display = 'flex';
    if (geoDiagnoseResult) geoDiagnoseResult.style.display = 'none';
    if (geoPlanResult) geoPlanResult.style.display = 'none';

    try {
        const keywords = Array.from(document.querySelectorAll('#geoKeywordsContainer .keyword-tag'))
            .map(tag => tag.textContent.replace('×', '').trim());
        
        const result = await apiRequest('/geo/optimization-plan', {
            method: 'POST',
            body: JSON.stringify({
                domain: domain,
                brand_name: brand,
                industry: industry,
                keywords: keywords,
                location: location
            })
        });
        
        if (result.success && result.data) {
            displayPlanResult(result.data);
            showMessage('优化方案生成成功', 'success');
        } else {
            showMessage(result.message || '生成失败', 'error');
        }
    } catch (error) {
        console.error('生成失败:', error);
        showMessage('生成请求失败: ' + error.message, 'error');
    } finally {
        if (diagnoseBtn) diagnoseBtn.disabled = false;
        if (planBtn) planBtn.disabled = false;
        if (geoLoading) geoLoading.style.display = 'none';
        if (geoPlanResult) geoPlanResult.style.display = 'block';
    }
}

/**
 * 自动生成关键词
 */
async function generateKeywords() {
    const brand = document.getElementById('geoBrand').value.trim();
    const industry = document.getElementById('geoIndustry').value;
    const location = document.getElementById('geoLocation').value.trim();
    
    if (!brand) {
        alert('请先填写品牌名称');
        return;
    }
    
    try {
        const result = await apiRequest('/geo/optimization-plan', {
            method: 'POST',
            body: JSON.stringify({
                domain: 'example.com',
                brand_name: brand,
                industry: industry,
                keywords: [],
                location: location
            })
        });
        
        if (result.success && result.data) {
            const keywords = result.data.keyword_matrix;
            const allKeywords = [
                ...(keywords.core_keywords || []),
                ...(keywords.long_tail_keywords || []).slice(0, 3),
                ...(keywords.location_keywords || [])
            ].filter((k, i, arr) => arr.indexOf(k) === i);
            
            const container = document.getElementById('geoKeywordsContainer');
            container.innerHTML = allKeywords.map(k => `<span class="keyword-tag">${k}</span>`).join('') + 
                '<input type="text" id="geoKeywordInput" class="form-control keyword-input" placeholder="输入关键词后按回车添加">';
            
            setupKeywordInput();
            showMessage('关键词自动生成成功', 'success');
        } else {
            showMessage(result.message || '生成失败', 'error');
        }
    } catch (error) {
        console.error('生成关键词失败:', error);
        showMessage('生成关键词失败: ' + error.message, 'error');
    }
}

function setupKeywordInput() {
    const input = document.getElementById('geoKeywordInput');
    if (input) {
        input.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && this.value.trim()) {
                const container = document.getElementById('geoKeywordsContainer');
                const tag = document.createElement('span');
                tag.className = 'keyword-tag';
                tag.textContent = this.value.trim();
                container.insertBefore(tag, this);
                this.value = '';
            }
        });
    }
}

/**
 * 显示诊断结果
 */
function displayDiagnoseResult(data) {
    const diagnoseContent = document.getElementById('diagnoseContent');
    if (!diagnoseContent) return;
    
    diagnoseContent.innerHTML = `
        <div class="diagnose-summary">
            <div class="diagnose-score">
                <div class="score-value">${data.overall_score || 0}</div>
                <div class="score-label">综合评分</div>
            </div>
            <div class="diagnose-info">
                <h4>${data.competitive_position?.split(' - ')[0] || '待分析'}</h4>
                <p>${data.competitive_position?.split(' - ')[1] || ''}</p>
                <p><strong>GEO准备度：${data.geo_readiness?.level || '未知'}</strong> - ${data.geo_readiness?.description || ''}</p>
            </div>
        </div>
        <div class="diagnose-details">
            <div class="detail-item">
                <div class="detail-value">${data.content_score || 0}</div>
                <div class="detail-label">内容质量</div>
            </div>
            <div class="detail-item">
                <div class="detail-value">${data.structure_score || 0}</div>
                <div class="detail-label">结构优化</div>
            </div>
            <div class="detail-item">
                <div class="detail-value">${data.authority_score || 0}</div>
                <div class="detail-label">权威性</div>
            </div>
            <div class="detail-item">
                <div class="detail-value">${data.technical_score || 0}</div>
                <div class="detail-label">技术性能</div>
            </div>
        </div>
        <h4 class="section-title">⚠️ 发现的问题</h4>
        <div class="issues-list">
            ${(data.issues || []).map(issue => `
                <div class="issue-item issue-${issue.severity || 'medium'}">
                    <span class="issue-severity">${issue.severity === 'high' ? '高' : issue.severity === 'medium' ? '中' : '低'}</span>
                    <div>
                        <strong>${issue.title || '未知问题'}</strong>
                        <p>${issue.description || ''}</p>
                    </div>
                </div>
            `).join('')}
        </div>
        <h4 class="section-title">💡 优化建议</h4>
        <div class="suggestions-grid">
            ${(data.suggestions || []).map(suggestion => `
                <div class="suggestion-card">
                    <div class="suggestion-header">
                        <span class="suggestion-category">${suggestion.category || '通用'}</span>
                    </div>
                    <h4>${suggestion.title || '优化建议'}</h4>
                    <p>${suggestion.description || ''}</p>
                    <div class="suggestion-action">${suggestion.action || ''}</div>
                    <div class="suggestion-impact">📈 预期效果：${suggestion.expected_impact || ''}</div>
                </div>
            `).join('')}
        </div>
    `;
}

/**
 * 显示优化方案结果
 */
function displayPlanResult(data) {
    // 填充方案概览
    const planScore = document.getElementById('planScore');
    const planTitle = document.getElementById('planTitle');
    const planDescription = document.getElementById('planDescription');
    const planExpectedEffect = document.getElementById('planExpectedEffect');
    
    if (planScore) planScore.textContent = data.expected_score || '85';
    if (planTitle) planTitle.textContent = data.title || 'GEO优化方案';
    if (planDescription) planDescription.textContent = data.description || '';
    if (planExpectedEffect) planExpectedEffect.textContent = data.expected_effect || '';
    
    // 填充品牌定位分析
    const planBrandName = document.getElementById('planBrandName');
    const planIndustry = document.getElementById('planIndustry');
    const planUsers = document.getElementById('planUsers');
    const planStrategy = document.getElementById('planStrategy');
    
    if (planBrandName) planBrandName.textContent = data.brand_name || '';
    if (planIndustry) planIndustry.textContent = data.industry || '';
    if (planUsers) planUsers.textContent = data.brand_positioning?.target_users || '';
    if (planStrategy) planStrategy.textContent = data.brand_positioning?.geo_strategy || '';
    
    // 填充关键词矩阵
    const planCoreKeywords = document.getElementById('planCoreKeywords');
    const planLongTailKeywords = document.getElementById('planLongTailKeywords');
    const planLocationKeywords = document.getElementById('planLocationKeywords');
    
    if (planCoreKeywords) {
        const coreKeywords = data.keyword_matrix?.core_keywords || [];
        planCoreKeywords.innerHTML = coreKeywords.map(k => `<span class="keyword-tag">${k}</span>`).join('');
    }
    if (planLongTailKeywords) {
        const longTailKeywords = data.keyword_matrix?.long_tail_keywords || [];
        planLongTailKeywords.innerHTML = longTailKeywords.map(k => `<span class="keyword-tag">${k}</span>`).join('');
    }
    if (planLocationKeywords) {
        const locationKeywords = data.keyword_matrix?.location_keywords || [];
        planLocationKeywords.innerHTML = locationKeywords.map(k => `<span class="keyword-tag">${k}</span>`).join('');
    }
    
    // 填充执行路线图
    const planMonth1 = document.getElementById('planMonth1');
    const planMonth23 = document.getElementById('planMonth23');
    const planOngoing = document.getElementById('planOngoing');
    
    if (planMonth1) {
        const month1 = data.execution_roadmap?.month_1 || [];
        planMonth1.innerHTML = month1.map(item => `<li>${item}</li>`).join('');
    }
    if (planMonth23) {
        const month23 = data.execution_roadmap?.month_2_3 || [];
        planMonth23.innerHTML = month23.map(item => `<li>${item}</li>`).join('');
    }
    if (planOngoing) {
        const ongoing = data.execution_roadmap?.ongoing || [];
        planOngoing.innerHTML = ongoing.map(item => `<li>${item}</li>`).join('');
    }
    
    // 填充效果预期
    const planCitation = document.getElementById('planCitation');
    const planRank = document.getElementById('planRank');
    const planConversion = document.getElementById('planConversion');
    
    if (planCitation) planCitation.textContent = data.expected_results?.ai_citation_increase || '+150%';
    if (planRank) planRank.textContent = data.expected_results?.local_rank_improvement || 'Top 3';
    if (planConversion) planConversion.textContent = data.expected_results?.conversion_rate_increase || '+30%';
    
    // 填充词条投入计划
    const keywordInvestment = data.keyword_investment || {};
    const investmentBudget = document.getElementById('investmentBudget');
    const investmentROI = document.getElementById('investmentROI');
    
    if (investmentBudget) investmentBudget.innerHTML = `<strong>${keywordInvestment.total_monthly_budget || ''}</strong>`;
    if (investmentROI) investmentROI.innerHTML = `<strong>${keywordInvestment.roi_expectation || ''}</strong>`;
    
    // 核心词条详情
    const coreKeywordsDetail = document.getElementById('coreKeywordsDetail');
    if (coreKeywordsDetail && keywordInvestment.core_keywords) {
        const core = keywordInvestment.core_keywords;
        coreKeywordsDetail.innerHTML = `
            <div class="investment-strategy">${core.strategy || ''}</div>
            <div class="investment-keywords">
                <h5>目标词条</h5>
                <div class="keyword-tags">${(core.keywords || []).map(k => `<span class="keyword-tag-small">${k}</span>`).join('')}</div>
            </div>
            <div class="investment-requirements">
                <h5>内容要求</h5>
                <ul>${(core.content_requirements || []).map(req => `<li>${req}</li>`).join('')}</ul>
            </div>
            <div class="investment-meta">
                <div class="investment-meta-item">
                    <span class="investment-meta-label">投放平台：</span>
                    <span class="investment-meta-value">${(core.platforms || []).join('、')}</span>
                </div>
                <div class="investment-meta-item">
                    <span class="investment-meta-label">更新频率：</span>
                    <span class="investment-meta-value">${core.frequency || ''}</span>
                </div>
                <div class="investment-meta-item">
                    <span class="investment-meta-label">预期效果：</span>
                    <span class="investment-meta-value">${core.expected_result || ''}</span>
                </div>
            </div>
        `;
    }
    
    // 长尾词条详情
    const longTailKeywordsDetail = document.getElementById('longTailKeywordsDetail');
    if (longTailKeywordsDetail && keywordInvestment.long_tail_keywords) {
        const longTail = keywordInvestment.long_tail_keywords;
        longTailKeywordsDetail.innerHTML = `
            <div class="investment-strategy">${longTail.strategy || ''}</div>
            <div class="investment-keywords">
                <h5>目标词条</h5>
                <div class="keyword-tags">${(longTail.keywords || []).map(k => `<span class="keyword-tag-small">${k}</span>`).join('')}</div>
            </div>
            <div class="investment-requirements">
                <h5>内容要求</h5>
                <ul>${(longTail.content_requirements || []).map(req => `<li>${req}</li>`).join('')}</ul>
            </div>
            <div class="investment-meta">
                <div class="investment-meta-item">
                    <span class="investment-meta-label">投放平台：</span>
                    <span class="investment-meta-value">${(longTail.platforms || []).join('、')}</span>
                </div>
                <div class="investment-meta-item">
                    <span class="investment-meta-label">更新频率：</span>
                    <span class="investment-meta-value">${longTail.frequency || ''}</span>
                </div>
                <div class="investment-meta-item">
                    <span class="investment-meta-label">预期效果：</span>
                    <span class="investment-meta-value">${longTail.expected_result || ''}</span>
                </div>
            </div>
        `;
    }
    
    // 地域词条详情
    const locationKeywordsDetail = document.getElementById('locationKeywordsDetail');
    if (locationKeywordsDetail && keywordInvestment.location_keywords) {
        const loc = keywordInvestment.location_keywords;
        locationKeywordsDetail.innerHTML = `
            <div class="investment-strategy">${loc.strategy || ''}</div>
            <div class="investment-keywords">
                <h5>目标词条</h5>
                <div class="keyword-tags">${(loc.keywords || []).map(k => `<span class="keyword-tag-small">${k}</span>`).join('')}</div>
            </div>
            <div class="investment-requirements">
                <h5>内容要求</h5>
                <ul>${(loc.content_requirements || []).map(req => `<li>${req}</li>`).join('')}</ul>
            </div>
            <div class="investment-meta">
                <div class="investment-meta-item">
                    <span class="investment-meta-label">投放平台：</span>
                    <span class="investment-meta-value">${(loc.platforms || []).join('、')}</span>
                </div>
                <div class="investment-meta-item">
                    <span class="investment-meta-label">更新频率：</span>
                    <span class="investment-meta-value">${loc.frequency || ''}</span>
                </div>
                <div class="investment-meta-item">
                    <span class="investment-meta-label">预期效果：</span>
                    <span class="investment-meta-value">${loc.expected_result || ''}</span>
                </div>
            </div>
        `;
    }
    
    // 行业词条详情
    const industryKeywordsDetail = document.getElementById('industryKeywordsDetail');
    if (industryKeywordsDetail && keywordInvestment.industry_terms) {
        const industry = keywordInvestment.industry_terms;
        industryKeywordsDetail.innerHTML = `
            <div class="investment-strategy">${industry.strategy || ''}</div>
            <div class="investment-keywords">
                <h5>目标词条</h5>
                <div class="keyword-tags">${(industry.keywords || []).map(k => `<span class="keyword-tag-small">${k}</span>`).join('')}</div>
            </div>
            <div class="investment-requirements">
                <h5>内容要求</h5>
                <ul>${(industry.content_requirements || []).map(req => `<li>${req}</li>`).join('')}</ul>
            </div>
            <div class="investment-meta">
                <div class="investment-meta-item">
                    <span class="investment-meta-label">投放平台：</span>
                    <span class="investment-meta-value">${(industry.platforms || []).join('、')}</span>
                </div>
                <div class="investment-meta-item">
                    <span class="investment-meta-label">更新频率：</span>
                    <span class="investment-meta-value">${industry.frequency || ''}</span>
                </div>
                <div class="investment-meta-item">
                    <span class="investment-meta-label">预期效果：</span>
                    <span class="investment-meta-value">${industry.expected_result || ''}</span>
                </div>
            </div>
        `;
    }
    
    // 填充数据喂养策略
    const dataFeeding = data.data_feeding || {};
    const feedingOverview = document.getElementById('feedingOverview');
    if (feedingOverview) feedingOverview.textContent = dataFeeding.overview || '';
    
    // 结构化数据投喂
    const structuredDataFeeding = document.getElementById('structuredDataFeeding');
    if (structuredDataFeeding && dataFeeding.structured_data) {
        const structured = dataFeeding.structured_data;
        structuredDataFeeding.innerHTML = `
            <p>${structured.description || ''}</p>
            ${(structured.methods || []).map(method => `
                <div class="method-detail">
                    <h5>${method.name}</h5>
                    <p><strong>实施方式：</strong>${method.implementation || ''}</p>
                    <p><strong>投放平台：</strong>${(method.platforms || []).join('、')}</p>
                    <p><strong>更新频率：</strong>${method.frequency || ''}</p>
                    <p><strong>预期效果：</strong>${method.impact || ''}</p>
                </div>
            `).join('')}
        `;
    }
    
    // 内容数据投喂
    const contentDataFeeding = document.getElementById('contentDataFeeding');
    if (contentDataFeeding && dataFeeding.content_data) {
        const content = dataFeeding.content_data;
        contentDataFeeding.innerHTML = `
            <p>${content.description || ''}</p>
            ${(content.methods || []).map(method => `
                <div class="method-detail">
                    <h5>${method.name}</h5>
                    <div class="content-types"><strong>内容类型：</strong><ul>${(method.content_types || []).map(type => `<li>${type}</li>`).join('')}</ul></div>
                    <div class="requirements"><strong>要求：</strong><ul>${(method.requirements || []).map(req => `<li>${req}</li>`).join('')}</ul></div>
                    <p><strong>投放平台：</strong>${(method.platforms || []).join('、')}</p>
                    <p><strong>更新频率：</strong>${method.frequency || ''}</p>
                    <p><strong>预期效果：</strong>${method.impact || ''}</p>
                </div>
            `).join('')}
        `;
    }
    
    // 社交信号投喂
    const socialSignalFeeding = document.getElementById('socialSignalFeeding');
    if (socialSignalFeeding && dataFeeding.social_signals) {
        const social = dataFeeding.social_signals;
        socialSignalFeeding.innerHTML = `
            <p>${social.description || ''}</p>
            ${(social.methods || []).map(method => `
                <div class="method-detail">
                    <h5>${method.name}</h5>
                    <p><strong>投放平台：</strong>${(method.platforms || []).join('、')}</p>
                    ${method.content_strategy ? `<div class="content-strategy"><strong>内容策略：</strong><ul>${(method.content_strategy || []).map(s => `<li>${s}</li>`).join('')}</ul></div>` : ''}
                    ${method.methods ? `<div class="methods"><strong>执行方法：</strong><ul>${(method.methods || []).map(m => `<li>${m}</li>`).join('')}</ul></div>` : ''}
                    <p><strong>更新频率：</strong>${method.frequency || ''}</p>
                    <p><strong>预期效果：</strong>${method.impact || ''}</p>
                </div>
            `).join('')}
        `;
    }
    
    // 技术数据投喂
    const technicalDataFeeding = document.getElementById('technicalDataFeeding');
    if (technicalDataFeeding && dataFeeding.technical_data) {
        const technical = dataFeeding.technical_data;
        technicalDataFeeding.innerHTML = `
            <p>${technical.description || ''}</p>
            ${(technical.methods || []).map(method => `
                <div class="method-detail">
                    <h5>${method.name}</h5>
                    <div class="tech-items"><ul>${(method.items || []).map(item => `<li>${item}</li>`).join('')}</ul></div>
                    <p><strong>预期效果：</strong>${method.impact || ''}</p>
                </div>
            `).join('')}
        `;
    }
    
    // 填充执行时间表
    const scheduleWeek12 = document.getElementById('scheduleWeek12');
    const scheduleWeek34 = document.getElementById('scheduleWeek34');
    const scheduleMonth23 = document.getElementById('scheduleMonth23');
    const scheduleOngoing = document.getElementById('scheduleOngoing');
    
    if (scheduleWeek12) {
        const week12 = dataFeeding.feeding_schedule?.week_1_2 || [];
        scheduleWeek12.innerHTML = week12.map(item => `<li>${item}</li>`).join('');
    }
    if (scheduleWeek34) {
        const week34 = dataFeeding.feeding_schedule?.week_3_4 || [];
        scheduleWeek34.innerHTML = week34.map(item => `<li>${item}</li>`).join('');
    }
    if (scheduleMonth23) {
        const month23 = dataFeeding.feeding_schedule?.month_2_3 || [];
        scheduleMonth23.innerHTML = month23.map(item => `<li>${item}</li>`).join('');
    }
    if (scheduleOngoing) {
        const ongoingSchedule = dataFeeding.feeding_schedule?.ongoing || [];
        scheduleOngoing.innerHTML = ongoingSchedule.map(item => `<li>${item}</li>`).join('');
    }
    
    // 填充成功指标
    const successMetrics = document.getElementById('successMetrics');
    if (successMetrics) {
        const metrics = dataFeeding.success_metrics || [];
        successMetrics.innerHTML = metrics.map(metric => `
            <div class="metric-card">
                <div class="metric-value">${metric}</div>
            </div>
        `).join('');
    }
    
    // 显示结果区域
    const geoPlanResult = document.getElementById('geoPlanResult');
    if (geoPlanResult) geoPlanResult.style.display = 'block';
}
