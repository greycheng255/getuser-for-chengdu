/**
 * 网站GEO诊断前端脚本
 */

const API_BASE_URL = 'http://localhost:5000/api';

// 工具函数
function showMessage(message, type = 'info') {
    const container = document.getElementById('messageContainer');
    if (!container) return;
    
    const el = document.createElement('div');
    el.className = `message message-${type}`;
    el.textContent = message;
    container.appendChild(el);
    
    setTimeout(() => el.remove(), 3000);
}

async function apiRequest(endpoint, options = {}) {
    const url = `${API_BASE_URL}${endpoint}`;
    const token = localStorage.getItem('geo_token');
    
    const config = {
        headers: {
            'Content-Type': 'application/json',
            ...options.headers
        },
        ...options
    };
    
    if (token) {
        config.headers['Authorization'] = `Bearer ${token}`;
    }
    
    try {
        const response = await fetch(url, config);
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.message || '请求失败');
        }
        
        return data;
    } catch (error) {
        console.error('API错误:', error);
        throw error;
    }
}

// 切换对比模式
function toggleCompareMode() {
    const checkbox = document.getElementById('compareMode');
    const section = document.getElementById('compareModeSection');
    section.style.display = checkbox.checked ? 'block' : 'none';
}

// 添加对比输入框
function addCompareInput() {
    const container = document.getElementById('compareInputs');
    const rows = container.querySelectorAll('.compare-input-row');
    
    if (rows.length >= 5) {
        showMessage('最多支持5个网站对比', 'warning');
        return;
    }
    
    const row = document.createElement('div');
    row.className = 'compare-input-row';
    row.innerHTML = `
        <input type="text" class="form-control" placeholder="网站${rows.length + 1}">
        <button onclick="this.parentElement.remove()">删除</button>
    `;
    container.appendChild(row);
}

// 开始诊断
async function startDiagnose() {
    const isCompareMode = document.getElementById('compareMode').checked;
    
    if (isCompareMode) {
        await startComparison();
    } else {
        await diagnoseSingle();
    }
}

// 单网站诊断
async function diagnoseSingle() {
    const url = document.getElementById('diagnoseUrl').value.trim();
    
    if (!url) {
        showMessage('请输入域名', 'warning');
        return;
    }
    
    // 显示加载
    document.getElementById('diagnoseLoading').classList.add('active');
    document.getElementById('diagnoseResult').classList.remove('active');
    document.getElementById('comparisonResult').classList.remove('active');
    document.getElementById('diagnoseBtn').disabled = true;
    
    try {
        const data = await apiRequest('/website/diagnose', {
            method: 'POST',
            body: JSON.stringify({ url })
        });
        
        if (data.success) {
            displayDiagnoseResult(data.data);
            showMessage('诊断完成', 'success');
        }
    } catch (error) {
        showMessage(error.message, 'error');
    } finally {
        document.getElementById('diagnoseLoading').classList.remove('active');
        document.getElementById('diagnoseBtn').disabled = false;
    }
}

// 多网站对比
async function startComparison() {
    const inputs = document.querySelectorAll('#compareInputs input');
    const urls = Array.from(inputs).map(input => input.value.trim()).filter(url => url);
    
    if (urls.length < 2) {
        showMessage('请至少输入两个网站进行对比', 'warning');
        return;
    }
    
    document.getElementById('diagnoseLoading').classList.add('active');
    document.getElementById('diagnoseResult').classList.remove('active');
    document.getElementById('comparisonResult').classList.remove('active');
    document.getElementById('diagnoseBtn').disabled = true;
    
    try {
        const data = await apiRequest('/website/compare', {
            method: 'POST',
            body: JSON.stringify({ urls })
        });
        
        if (data.success) {
            displayComparisonResult(data.data);
            showMessage('对比分析完成', 'success');
        }
    } catch (error) {
        showMessage(error.message, 'error');
    } finally {
        document.getElementById('diagnoseLoading').classList.remove('active');
        document.getElementById('diagnoseBtn').disabled = false;
    }
}

// 显示诊断结果
function displayDiagnoseResult(result) {
    const container = document.getElementById('diagnoseResult');
    container.classList.add('active');
    
    // 评分概览
    const scoreOverview = document.getElementById('scoreOverview');
    const overallClass = result.scores.overall >= 80 ? 'excellent' : 
                         result.scores.overall >= 60 ? 'good' :
                         result.scores.overall >= 40 ? 'average' : 'poor';
    
    scoreOverview.innerHTML = `
        <div class="score-card overall">
            <div class="score-circle-large ${overallClass}">
                <span class="score-value-large">${result.scores.overall}</span>
            </div>
            <div class="score-title">综合评分</div>
            <div class="score-label-large">GEO准备度: ${result.geo_readiness.level}</div>
        </div>
        <div class="score-card">
            <div class="score-circle-large ${result.scores.content >= 60 ? 'good' : 'poor'}">
                <span class="score-value-large">${result.scores.content}</span>
            </div>
            <div class="score-title">内容质量</div>
        </div>
        <div class="score-card">
            <div class="score-circle-large ${result.scores.structure >= 60 ? 'good' : 'poor'}">
                <span class="score-value-large">${result.scores.structure}</span>
            </div>
            <div class="score-title">结构优化</div>
        </div>
        <div class="score-card">
            <div class="score-circle-large ${result.scores.authority >= 60 ? 'good' : 'poor'}">
                <span class="score-value-large">${result.scores.authority}</span>
            </div>
            <div class="score-title">权威性</div>
        </div>
        <div class="score-card">
            <div class="score-circle-large ${result.scores.technical >= 60 ? 'good' : 'poor'}">
                <span class="score-value-large">${result.scores.technical}</span>
            </div>
            <div class="score-title">技术性能</div>
        </div>
    `;
    
    // 竞争定位
    const positionClass = result.scores.overall >= 80 ? 'leader' :
                          result.scores.overall >= 60 ? 'challenger' :
                          result.scores.overall >= 40 ? 'follower' : 'laggard';
    
    document.getElementById('positionContent').innerHTML = `
        <div class="position-badge ${positionClass}">${result.competitive_position.split(' - ')[0]}</div>
        <p>${result.competitive_position.split(' - ')[1]}</p>
        <div style="margin-top: 1rem; padding: 1rem; background: #f8fafc; border-radius: 8px;">
            <strong>下一步行动：</strong>${result.geo_readiness.next_steps}
        </div>
    `;
    
    // 优先级行动
    const priorityList = document.getElementById('priorityList');
    priorityList.innerHTML = result.priority_actions.map((action, index) => `
        <li>
            <span class="priority-number">${index + 1}</span>
            <span>${action}</span>
        </li>
    `).join('');
    
    // 基本信息
    const basicInfo = document.getElementById('basicInfo');
    basicInfo.innerHTML = `
        <div class="info-item">
            <span class="info-label">域名</span>
            <span class="info-value">${result.domain}</span>
        </div>
        <div class="info-item">
            <span class="info-label">页面标题</span>
            <span class="info-value">${result.basic_info.title || 'N/A'}</span>
        </div>
        <div class="info-item">
            <span class="info-label">总字数</span>
            <span class="info-value">${result.basic_info.word_count.toLocaleString()}</span>
        </div>
        <div class="info-item">
            <span class="info-label">加载时间</span>
            <span class="info-value">${result.basic_info.load_time.toFixed(2)}s</span>
        </div>
        <div class="info-item">
            <span class="info-label">SSL证书</span>
            <span class="info-value">${result.basic_info.ssl_valid ? '✅ 有效' : '❌ 无效'}</span>
        </div>
        <div class="info-item">
            <span class="info-label">标题层级</span>
            <span class="info-value">${result.basic_info.headings_count}个</span>
        </div>
        <div class="info-item">
            <span class="info-label">链接数量</span>
            <span class="info-value">${result.basic_info.links_count}个</span>
        </div>
        <div class="info-item">
            <span class="info-label">Schema标记</span>
            <span class="info-value">${result.basic_info.schema_count}个</span>
        </div>
    `;
    
    // 问题列表
    const issuesList = document.getElementById('issuesList');
    if (result.issues.length > 0) {
        issuesList.innerHTML = result.issues.map(issue => `
            <div class="issue-item ${issue.severity}">
                <span class="issue-severity">${issue.severity === 'high' ? '高' : issue.severity === 'medium' ? '中' : '低'}</span>
                <div class="issue-content">
                    <h4>${issue.title}</h4>
                    <p>${issue.description}</p>
                </div>
            </div>
        `).join('');
    } else {
        issuesList.innerHTML = '<p style="color: #10b981;">🎉 未发现明显问题！</p>';
    }
    
    // 优化建议
    const suggestionsGrid = document.getElementById('suggestionsGrid');
    suggestionsGrid.innerHTML = result.suggestions.map(suggestion => `
        <div class="suggestion-card priority-${suggestion.priority}">
            <div class="suggestion-header">
                <span class="suggestion-category">${suggestion.category}</span>
                <span class="suggestion-priority">${suggestion.priority === 'high' ? '高优先级' : suggestion.priority === 'medium' ? '中优先级' : '低优先级'}</span>
            </div>
            <h4>${suggestion.title}</h4>
            <p>${suggestion.description}</p>
            <div class="suggestion-action">
                <strong>行动：</strong>${suggestion.action}
            </div>
            <div class="suggestion-impact">
                📈 预期效果：${suggestion.expected_impact}
            </div>
        </div>
    `).join('');
}

// 显示对比结果
function displayComparisonResult(data) {
    const container = document.getElementById('comparisonResult');
    container.classList.add('active');
    
    // 对比表格
    const tbody = document.getElementById('comparisonTableBody');
    tbody.innerHTML = data.ranking.map((site, index) => {
        const scoreClass = site.scores.overall >= 80 ? 'high' : site.scores.overall >= 60 ? 'medium' : 'low';
        return `
            <tr class="rank-${index + 1}">
                <td>${index + 1}</td>
                <td><strong>${site.domain}</strong></td>
                <td class="score-cell ${scoreClass}">${site.scores.overall}</td>
                <td>${site.scores.content}</td>
                <td>${site.scores.structure}</td>
                <td>${site.scores.authority}</td>
                <td>${site.scores.technical}</td>
            </tr>
        `;
    }).join('');
    
    // 最佳实践
    const bestPracticesContent = document.getElementById('bestPracticesContent');
    bestPracticesContent.innerHTML = data.best_practices.map(practice => `
        <div class="practice-item">
            <div class="practice-icon">🏆</div>
            <div class="practice-content">
                <h4>${practice.aspect}最佳</h4>
                <p>${practice.tip}</p>
            </div>
            <div class="practice-leader">${practice.leader} (${practice.score}分)</div>
        </div>
    `).join('');
    
    // 差距分析
    const gaps = data.gaps_analysis;
    bestPracticesContent.innerHTML += `
        <div style="margin-top: 2rem; padding: 1.5rem; background: #f8fafc; border-radius: 12px;">
            <h4 style="margin-bottom: 1rem;">📊 差距分析</h4>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1rem;">
                <div>
                    <div style="font-size: 0.875rem; color: #64748b;">平均分</div>
                    <div style="font-size: 1.5rem; font-weight: bold;">${gaps.average_score}</div>
                </div>
                <div>
                    <div style="font-size: 0.875rem; color: #64748b;">分数差距</div>
                    <div style="font-size: 1.5rem; font-weight: bold;">${gaps.score_range}</div>
                </div>
                <div>
                    <div style="font-size: 0.875rem; color: #64748b;">提升空间</div>
                    <div style="font-size: 1.5rem; font-weight: bold; color: #10b981;">${gaps.improvement_potential}%</div>
                </div>
            </div>
        </div>
    `;
}

// 加载诊断历史
async function loadDiagnosisHistory() {
    const token = localStorage.getItem('geo_token');
    if (!token) return;
    
    try {
        const data = await apiRequest('/website/history?limit=10');
        
        if (data.success && data.data.length > 0) {
            const section = document.getElementById('historySection');
            const list = document.getElementById('historyList');
            
            section.style.display = 'block';
            list.innerHTML = data.data.map(item => {
                const scoreClass = item.overall_score >= 80 ? 'high' : item.overall_score >= 60 ? 'medium' : 'low';
                return `
                    <div class="history-item" onclick="loadHistoryDetail(${item.id})">
                        <div>
                            <div class="history-domain">${item.domain}</div>
                            <div class="history-date">${new Date(item.created_at).toLocaleString()}</div>
                        </div>
                        <span class="history-score ${scoreClass}">${item.overall_score}分</span>
                    </div>
                `;
            }).join('');
        }
    } catch (error) {
        console.error('加载历史失败:', error);
    }
}

// 页面加载
window.addEventListener('DOMContentLoaded', () => {
    loadDiagnosisHistory();
    
    // 回车键提交
    document.getElementById('diagnoseUrl')?.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') startDiagnose();
    });
});
