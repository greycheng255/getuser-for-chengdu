/**
 * GEO系统前端应用 - 真实API版本
 * 与后端API交互，使用真实数据库
 */

// API基础URL
const API_BASE_URL = 'http://localhost:5000/api';

// 全局状态
const state = {
    token: localStorage.getItem('geo_token'),
    user: JSON.parse(localStorage.getItem('geo_user') || 'null'),
    currentSection: 'home'
};

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
 * 用户注册
 */
async function register(username, password, email = '') {
    try {
        const data = await apiRequest('/auth/register', {
            method: 'POST',
            body: JSON.stringify({ username, password, email })
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
            state.user = { id: data.user_id, username: data.username };
            localStorage.setItem('geo_token', data.access_token);
            localStorage.setItem('geo_user', JSON.stringify(state.user));
            showMessage('登录成功', 'success');
            updateUIForLoggedInUser();
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
async function logout() {
    try {
        await apiRequest('/auth/logout', {
            method: 'POST'
        });
    } catch (e) {
        // 忽略错误
    }
    
    state.token = null;
    state.user = null;
    localStorage.removeItem('geo_token');
    localStorage.removeItem('geo_user');
    showMessage('已登出', 'info');
    updateUIForLoggedOutUser();
    showSection('home');
}

/**
 * 获取用户信息
 */
async function getUserProfile() {
    try {
        const data = await apiRequest('/auth/profile');
        if (data.success) {
            state.user = data.data;
            localStorage.setItem('geo_user', JSON.stringify(state.user));
            return data.data;
        }
    } catch (error) {
        console.error('获取用户信息失败:', error);
    }
    return null;
}

/**
 * 更新UI为登录状态
 */
function updateUIForLoggedInUser() {
    const userInfo = document.querySelector('.user-info');
    if (userInfo && state.user) {
        userInfo.innerHTML = `
            <span>👤 ${state.user.username}</span>
            <button onclick="logout()" class="btn btn-sm btn-secondary">退出</button>
        `;
    }
}

/**
 * 更新UI为登出状态
 */
function updateUIForLoggedOutUser() {
    const userInfo = document.querySelector('.user-info');
    if (userInfo) {
        userInfo.innerHTML = `
            <button onclick="showLoginModal()" class="btn btn-sm btn-primary">登录</button>
        `;
    }
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
            
            // 刷新历史记录
            if (state.token) {
                loadGenerationHistory();
            }
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
 * 加载生成历史
 */
async function loadGenerationHistory() {
    if (!state.token) return;
    
    try {
        const data = await apiRequest('/content/history?limit=10');
        if (data.success && data.data.length > 0) {
            // 可以在这里显示历史记录侧边栏
            console.log('生成历史:', data.data);
        }
    } catch (error) {
        console.error('加载历史失败:', error);
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
    if (!state.token) {
        showMessage('请先登录以记录指标', 'warning');
        return false;
    }
    
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
    if (!state.token) {
        showMessage('请先登录以查看报告', 'warning');
        return;
    }
    
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

// ==================== 登录弹窗 ====================

function showLoginModal() {
    // 创建登录弹窗
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.innerHTML = `
        <div class="modal-content">
            <div class="modal-header">
                <h3>用户登录</h3>
                <button onclick="this.closest('.modal').remove()" class="btn-close">&times;</button>
            </div>
            <form id="loginForm">
                <div class="form-group">
                    <label>用户名</label>
                    <input type="text" id="loginUsername" class="form-control" required>
                </div>
                <div class="form-group">
                    <label>密码</label>
                    <input type="password" id="loginPassword" class="form-control" required>
                </div>
                <button type="submit" class="btn btn-primary btn-block">登录</button>
            </form>
            <p style="text-align: center; margin-top: 1rem;">
                还没有账号？<a href="#" onclick="showRegisterModal(); return false;">立即注册</a>
            </p>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    // 绑定登录表单
    modal.querySelector('#loginForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        const username = document.getElementById('loginUsername').value;
        const password = document.getElementById('loginPassword').value;
        
        if (await login(username, password)) {
            modal.remove();
        }
    });
}

function showRegisterModal() {
    // 移除登录弹窗
    document.querySelector('.modal')?.remove();
    
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.innerHTML = `
        <div class="modal-content">
            <div class="modal-header">
                <h3>用户注册</h3>
                <button onclick="this.closest('.modal').remove()" class="btn-close">&times;</button>
            </div>
            <form id="registerForm">
                <div class="form-group">
                    <label>用户名</label>
                    <input type="text" id="regUsername" class="form-control" required>
                </div>
                <div class="form-group">
                    <label>密码</label>
                    <input type="password" id="regPassword" class="form-control" required minlength="6">
                </div>
                <div class="form-group">
                    <label>邮箱（可选）</label>
                    <input type="email" id="regEmail" class="form-control">
                </div>
                <button type="submit" class="btn btn-primary btn-block">注册</button>
            </form>
            <p style="text-align: center; margin-top: 1rem;">
                已有账号？<a href="#" onclick="showLoginModal(); return false;">立即登录</a>
            </p>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    // 绑定注册表单
    modal.querySelector('#registerForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        const username = document.getElementById('regUsername').value;
        const password = document.getElementById('regPassword').value;
        const email = document.getElementById('regEmail').value;
        
        if (await register(username, password, email)) {
            modal.remove();
            showLoginModal();
        }
    });
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
    
    // 检查登录状态
    if (state.token) {
        getUserProfile().then(() => {
            updateUIForLoggedInUser();
            loadGenerationHistory();
        });
    } else {
        updateUIForLoggedOutUser();
    }
    
    // 显示首页
    showSection('home');
});
