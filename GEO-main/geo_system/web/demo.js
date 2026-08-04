/**
 * GEO系统演示模式
 * 无需后端即可预览界面功能
 */

// 模拟API响应
const mockAPI = {
    // 模拟内容生成
    generateContent: (formData) => {
        return new Promise((resolve) => {
            setTimeout(() => {
                resolve({
                    success: true,
                    data: {
                        title: formData.title,
                        platform: formData.platform,
                        outline: [
                            { "level": 1, "title": "引言：AI搜索时代的挑战与机遇" },
                            { "level": 2, "title": "传统SEO的局限性" },
                            { "level": 2, "title": "GEO的核心理念" },
                            { "level": 1, "title": "ERE框架详解" },
                            { "level": 2, "title": "Entity（实体）定义与构建" },
                            { "level": 3, "title": "核心概念识别" },
                            { "level": 3, "title": "实体关系图谱" },
                            { "level": 2, "title": "Relation（关系）建立" },
                            { "level": 2, "title": "Evidence（证据）收集" },
                            { "level": 1, "title": "实战案例：" + formData.brandName + "的GEO实践" },
                            { "level": 2, "title": "背景分析" },
                            { "level": 2, "title": "实施过程" },
                            { "level": 2, "title": "成果展示" },
                            { "level": 1, "title": "总结与展望" }
                        ],
                        prompt: `你是一位专业的GEO内容策略专家。请根据以下要求创作一篇高质量的GEO优化文章：

文章标题：${formData.title}
目标平台：${formData.platform}
目标字数：${formData.wordCount}字

品牌信息：
- 品牌名称：${formData.brandName}
- 所属行业：${formData.industry}
- 专业领域：${formData.expertise}

要求：
1. 遵循ERE框架（实体-关系-证据）
2. 使用清晰的层级结构
3. 包含具体数据和案例
4. 自然融入品牌信息
5. 适合AI引用和总结`
                    },
                    message: '内容生成成功（演示模式）'
                });
            }, 1500);
        });
    },

    // 模拟内容分析
    analyzeContent: (content) => {
        return new Promise((resolve) => {
            setTimeout(() => {
                const wordCount = content.length;
                const hasStructure = content.includes('##') || content.includes('**');
                const hasData = /\d+%|\d+个|\d+元/.test(content);
                const hasCitation = content.includes('根据') || content.includes('数据显示');

                const structureScore = hasStructure ? 85 : 60;
                const citationScore = hasCitation ? 80 : 55;
                const readabilityScore = wordCount > 500 ? 80 : 65;
                const authorityScore = hasData ? 85 : 60;

                const overallScore = Math.round((structureScore + citationScore + readabilityScore + authorityScore) / 4);

                resolve({
                    success: true,
                    data: {
                        overall_score: overallScore,
                        structure_score: structureScore,
                        citation_score: citationScore,
                        readability_score: readabilityScore,
                        authority_score: authorityScore,
                        geo_compliance: overallScore >= 75 ? 'high' : overallScore >= 60 ? 'medium' : 'low',
                        issues: !hasStructure ? ['缺少清晰的层级结构'] : [],
                        suggestions: [
                            '增加更多数据支撑',
                            '优化段落长度，提升可读性',
                            '添加更多引用来源',
                            '强化ERE框架结构'
                        ]
                    },
                    message: '分析完成（演示模式）'
                });
            }, 1200);
        });
    },

    // 模拟内容优化
    optimizeContent: (content, level) => {
        return new Promise((resolve) => {
            setTimeout(() => {
                const scoreBefore = 65;
                const improvement = level === 'light' ? 10 : level === 'medium' ? 20 : 30;
                const scoreAfter = Math.min(95, scoreBefore + improvement);

                resolve({
                    success: true,
                    data: {
                        optimized_content: `【优化后的内容】\n\n${content}\n\n---\n\n【优化说明】\n1. 添加了清晰的层级标题\n2. 增加了数据引用和来源\n3. 优化了段落结构\n4. 强化了ERE框架\n5. 提升了可读性和专业性`,
                        score_before: scoreBefore,
                        score_after: scoreAfter,
                        improvements: [
                            '优化了内容结构，添加层级标题',
                            '增加了数据支撑和引用来源',
                            '改进了表达方式，提升可读性',
                            '强化了ERE框架结构',
                            '添加了具体的实施建议'
                        ]
                    },
                    message: '优化完成（演示模式）'
                });
            }, 1500);
        });
    },

    // 模拟ROI计算
    calculateROI: (params) => {
        return new Promise((resolve) => {
            setTimeout(() => {
                const totalInvestment = params.content_investment + params.technology_investment + params.personnel_investment;
                const monthlyTraffic = 10000;
                const conversionRate = params.conversion_rate / 100;
                const newCustomers = Math.round(monthlyTraffic * conversionRate * (params.ai_citation_increase / 100) * 12);
                const revenue = newCustomers * params.avg_customer_value;
                const netProfit = revenue - totalInvestment;
                const roiPercentage = totalInvestment > 0 ? (netProfit / totalInvestment) * 100 : 0;
                const paybackMonths = netProfit > 0 ? Math.ceil(totalInvestment / (netProfit / 12)) : 999;

                resolve({
                    success: true,
                    data: {
                        total_investment: totalInvestment,
                        revenue: revenue,
                        net_profit: netProfit,
                        roi_percentage: parseFloat(roiPercentage.toFixed(1)),
                        payback_period_months: paybackMonths,
                        new_customers: newCustomers
                    },
                    message: 'ROI计算完成（演示模式）'
                });
            }, 1000);
        });
    },

    // 模拟指标记录
    recordMetrics: (metrics) => {
        return new Promise((resolve) => {
            setTimeout(() => {
                resolve({
                    success: true,
                    message: '指标记录成功（演示模式）'
                });
            }, 500);
        });
    },

    // 模拟获取报告
    getMetricsReport: (type) => {
        return new Promise((resolve) => {
            setTimeout(() => {
                resolve({
                    success: true,
                    data: {
                        basic_metrics: {
                            ai_citation_rate: { current: 45.5, change: 5.5 },
                            brand_mention_rate: { current: 60.0, change: 5.0 },
                            answer_space_coverage: { current: 0.35, change: 0.05 },
                            visibility_score: { current: 65.5, change: 5.5 }
                        },
                        recommendations: [
                            { priority: 'high', suggestion: '增加高质量内容产出，提升AI引用率' },
                            { priority: 'medium', suggestion: '优化官网权威性，添加更多Schema标记' },
                            { priority: 'medium', suggestion: '扩大信源覆盖范围，增加行业媒体曝光' },
                            { priority: 'low', suggestion: '持续监测竞争对手动态' }
                        ]
                    },
                    message: '报告生成成功（演示模式）'
                });
            }, 800);
        });
    },

    // 获取信源金字塔
    getAuthorityPyramid: () => {
        return new Promise((resolve) => {
            setTimeout(() => {
                resolve({
                    success: true,
                    data: {
                        levels: {
                            1: { name: '官网', weight: 0.4, description: '品牌官方网站' },
                            2: { name: '权威媒体', weight: 0.3, description: '行业权威媒体' },
                            3: { name: '行业社区', weight: 0.2, description: '专业社区平台' },
                            4: { name: '社交平台', weight: 0.1, description: '社交媒体' }
                        }
                    },
                    message: '获取成功'
                });
            }, 500);
        });
    }
};

// 覆盖原有的API请求函数
const originalApiRequest = window.apiRequest;

window.apiRequest = async function(endpoint, options = {}) {
    // 演示模式：使用模拟API
    console.log('演示模式:', endpoint, options);

    try {
        const data = options.body ? JSON.parse(options.body) : {};

        switch (endpoint) {
            case '/content/generate':
                return await mockAPI.generateContent({
                    title: data.title,
                    brandName: data.brand_info?.name || '品牌',
                    industry: data.brand_info?.industry || 'AI营销',
                    expertise: data.brand_info?.expertise?.join('\n') || 'GEO\nAI搜索优化',
                    platform: data.target_platform || 'chatgpt',
                    wordCount: data.word_count || 3000
                });

            case '/content/analyze':
                return await mockAPI.analyzeContent(data.content);

            case '/content/optimize':
                return await mockAPI.optimizeContent(data.content, data.optimization_level);

            case '/roi/calculate':
                return await mockAPI.calculateROI(data);

            case '/metrics/record':
                return await mockAPI.recordMetrics(data);

            case '/metrics/report':
                const url = new URL('http://localhost' + endpoint);
                const reportType = url.searchParams.get('type') || 'monthly';
                return await mockAPI.getMetricsReport(reportType);

            case '/authority/pyramid':
                return await mockAPI.getAuthorityPyramid();

            default:
                return { success: false, message: '演示模式不支持此接口' };
        }
    } catch (error) {
        console.error('演示模式错误:', error);
        return { success: false, message: error.message };
    }
};

// 显示演示模式提示
window.addEventListener('DOMContentLoaded', () => {
    const banner = document.createElement('div');
    banner.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        color: white;
        text-align: center;
        padding: 8px;
        font-size: 14px;
        z-index: 9999;
    `;
    banner.innerHTML = '🎮 演示模式 - 所有数据为模拟数据，无需后端服务 | <a href="#" style="color: #ffd700; text-decoration: underline;">了解如何启动完整服务</a>';

    banner.querySelector('a').addEventListener('click', (e) => {
        e.preventDefault();
        alert('启动完整服务需要：\n\n1. 安装Python 3.8+\n2. 安装依赖: pip install -r backend/requirements.txt\n3. 启动后端: cd backend && python app.py\n4. 启动前端: cd web && python -m http.server 8080\n\n或使用 start.bat 一键启动');
    });

    document.body.appendChild(banner);

    // 调整主内容区位置
    document.querySelector('.main-content').style.marginTop = '36px';
});

// GEO优化专家 - 网站诊断
async function runGeoDiagnose() {
    console.log('runGeoDiagnose called');
    
    // 获取按钮元素
    const diagnoseBtn = document.querySelector('.action-buttons .btn-primary:first-of-type');
    const planBtn = document.querySelector('.action-buttons .btn-primary:last-of-type');
    
    // 获取DOM元素
    const brand = document.getElementById('geoBrand');
    const domain = document.getElementById('geoDomain');
    const geoLoading = document.getElementById('geoLoading');
    const geoDiagnoseResult = document.getElementById('geoDiagnoseResult');
    const geoPlanResult = document.getElementById('geoPlanResult');
    const diagnoseContent = document.getElementById('diagnoseContent');
    
    console.log('Elements:', { brand, domain, geoLoading, geoDiagnoseResult, geoPlanResult, diagnoseContent });
    
    // 验证表单元素
    if (!brand || !domain) {
        showMessage('找不到表单元素', 'error');
        return;
    }
    
    const brandValue = brand.value.trim();
    const domainValue = domain.value.trim();
    
    console.log('Form values:', { brand: brandValue, domain: domainValue });
    
    // 验证表单数据
    if (!brandValue || !domainValue) {
        showMessage('请填写品牌名称和网站域名', 'error');
        return;
    }
    
    // 禁用按钮
    if (diagnoseBtn) diagnoseBtn.disabled = true;
    if (planBtn) planBtn.disabled = true;
    
    // 显示加载状态
    if (geoLoading) {
        geoLoading.style.display = 'flex';
    }
    if (geoDiagnoseResult) {
        geoDiagnoseResult.style.display = 'none';
    }
    if (geoPlanResult) {
        geoPlanResult.style.display = 'none';
    }

    try {
        // 调用真实API
        const response = await fetch('http://localhost:5000/api/website/diagnose', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: domainValue, brand_name: brandValue })
        });
        
        const result = await response.json();
        console.log('API result:', result);
        
        if (result.success && result.data) {
            displayDiagnoseResult(result.data);
            showMessage('网站诊断完成', 'success');
        } else {
            // API返回失败，使用模拟数据
            showMockDiagnoseResult(diagnoseContent, brandValue, domainValue);
            showMessage('诊断完成（演示模式）', 'info');
        }
        
    } catch (error) {
        console.error('诊断失败:', error);
        // 网络错误时使用模拟数据
        showMockDiagnoseResult(diagnoseContent, brandValue, domainValue);
        showMessage('诊断完成（演示模式）', 'info');
    } finally {
        // 获取按钮元素
        const diagnoseBtn = document.querySelector('.action-buttons .btn-primary:first-of-type');
        const planBtn = document.querySelector('.action-buttons .btn-primary:last-of-type');
        
        // 启用按钮
        if (diagnoseBtn) diagnoseBtn.disabled = false;
        if (planBtn) planBtn.disabled = false;
        
        // 隐藏加载状态
        const geoLoading = document.getElementById('geoLoading');
        const geoDiagnoseResult = document.getElementById('geoDiagnoseResult');
        if (geoLoading) {
            geoLoading.style.display = 'none';
        }
        if (geoDiagnoseResult) {
            geoDiagnoseResult.style.display = 'block';
        }
    }
}

// GEO优化专家 - 生成优化方案
async function generateGeoPlan() {
    console.log('generateGeoPlan called');
    
    // 获取按钮元素
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
    
    // 获取DOM元素
    const geoLoading = document.getElementById('geoLoading');
    const geoDiagnoseResult = document.getElementById('geoDiagnoseResult');
    const geoPlanResult = document.getElementById('geoPlanResult');
    
    // 禁用按钮
    if (diagnoseBtn) diagnoseBtn.disabled = true;
    if (planBtn) planBtn.disabled = true;
    
    // 显示加载状态
    if (geoLoading) geoLoading.style.display = 'flex';
    if (geoDiagnoseResult) geoDiagnoseResult.style.display = 'none';
    if (geoPlanResult) geoPlanResult.style.display = 'none';

    try {
        const keywords = Array.from(document.querySelectorAll('#geoKeywordsContainer .keyword-tag'))
            .map(tag => tag.textContent.replace('×', '').trim());
        
        console.log('Generating plan with:', { brand, domain, industry, keywords, location });
        
        // 调用真实API
        const response = await fetch('http://localhost:5000/api/geo/optimization-plan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                domain: domain,
                brand_name: brand,
                industry: industry,
                keywords: keywords,
                location: location
            })
        });
        
        const result = await response.json();
        console.log('API result:', result);
        
        if (result.success && result.data) {
            displayPlanResult(result.data);
            showMessage('优化方案生成成功', 'success');
        } else {
            // API返回失败，使用模拟数据
            showMockPlanResult(brand, industry, keywords, location);
            showMessage('优化方案生成成功（演示模式）', 'info');
        }
    } catch (error) {
        console.error('生成失败:', error);
        // 网络错误时使用模拟数据
        const keywords = Array.from(document.querySelectorAll('#geoKeywordsContainer .keyword-tag'))
            .map(tag => tag.textContent.replace('×', '').trim());
        showMockPlanResult(brand, industry, keywords, location);
        showMessage('优化方案生成成功（演示模式）', 'info');
    } finally {
        // 启用按钮
        if (diagnoseBtn) diagnoseBtn.disabled = false;
        if (planBtn) planBtn.disabled = false;
        
        // 隐藏加载状态
        if (geoLoading) geoLoading.style.display = 'none';
        if (geoPlanResult) geoPlanResult.style.display = 'block';
    }
}

// GEO优化专家 - 自动生成关键词
async function generateKeywords() {
    const brand = document.getElementById('geoBrand').value.trim();
    const industry = document.getElementById('geoIndustry').value;
    const location = document.getElementById('geoLocation').value.trim();
    
    if (!brand) {
        alert('请先填写品牌名称');
        return;
    }
    
    try {
        const response = await fetch('http://localhost:5000/api/geo/optimization-plan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                domain: 'example.com',
                brand_name: brand,
                industry: industry,
                keywords: [],
                location: location
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
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
        generateMockKeywords(brand, industry, location);
    }
}

function generateMockKeywords(brand, industry, location) {
    const keywordTemplates = {
        '家具家居': [brand + '全屋定制', brand + '整体衣柜', '橱柜设计', '家具定制', location + '装修', '定制家具'],
        '教育培训': [brand + '培训', '在线教育', '职业培训', location + '学习', '课程辅导'],
        '医疗健康': ['健康咨询', '体检服务', '专科诊疗', location + '医院', '健康管理'],
        '电商零售': [brand + '商城', '在线购物', '品质保障', location + '特产', '优惠促销'],
        '科技软件': ['软件开发', '技术咨询', '系统集成', brand + '科技', 'IT服务'],
        '其他': [brand, brand + '服务', location + brand, industry + '解决方案']
    };
    
    const keywords = keywordTemplates[industry] || keywordTemplates['其他'];
    const container = document.getElementById('geoKeywordsContainer');
    container.innerHTML = keywords.map(k => `<span class="keyword-tag">${k}</span>`).join('') + 
        '<input type="text" id="geoKeywordInput" class="form-control keyword-input" placeholder="输入关键词后按回车添加">';
    
    setupKeywordInput();
    showMessage('关键词自动生成成功（演示模式）', 'success');
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

// GEO优化专家 - 显示诊断结果（真实数据）
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

// GEO优化专家 - 显示模拟诊断结果
function showMockDiagnoseResult(container, brand, domain) {
    if (!container) return;
    
    const scores = {
        content: Math.floor(Math.random() * 30) + 60,
        structure: Math.floor(Math.random() * 30) + 55,
        authority: Math.floor(Math.random() * 30) + 50,
        technical: Math.floor(Math.random() * 25) + 70
    };
    const overall = Math.round((scores.content * 0.3 + scores.structure * 0.25 + scores.authority * 0.25 + scores.technical * 0.2));
    
    const competitivePositions = [
        '追赶者 - 网站具备基础GEO能力，需要针对性优化',
        '竞争者 - 网站有一定GEO基础，竞争处于中等水平',
        '领先者 - 网站GEO表现良好，具备竞争优势'
    ];
    const positionIndex = overall >= 80 ? 2 : overall >= 60 ? 1 : 0;
    
    const readinessLevels = [
        { level: '低', description: '需要全面优化' },
        { level: '中', description: '具备基础，需要针对性改进' },
        { level: '高', description: '准备度良好，持续优化即可' }
    ];
    const readiness = readinessLevels[positionIndex];
    
    const issues = [
        { severity: 'high', title: '内容量不足', description: '页面字数较少，建议至少1000字以上' },
        { severity: 'high', title: '缺少Schema.org标记', description: '结构化数据帮助AI理解内容语义' },
        { severity: 'medium', title: '标题层级不完善', description: '建议添加更多H2/H3标题' },
        { severity: 'low', title: '图片缺少alt属性', description: '图片应添加描述性alt文本' }
    ];
    
    const suggestions = [
        { category: '内容', title: '扩充内容深度', description: '增加详细的产品介绍、使用案例、FAQ等内容', action: '撰写至少2000字的深度内容', expected_impact: '提升AI引用率20-30%' },
        { category: '权威性', title: '添加结构化数据', description: '实施Schema.org标记帮助AI理解内容', action: '添加Organization、Product类型的Schema', expected_impact: '显著提升AI引用概率' },
        { category: '技术', title: '优化页面结构', description: '使用H2/H3标签创建清晰的内容层级', action: '添加3-5个H2小标题', expected_impact: '提升可读性和AI理解度' }
    ];
    
    container.innerHTML = `
        <div class="diagnose-summary">
            <div class="diagnose-score">
                <div class="score-value">${overall}</div>
                <div class="score-label">综合评分</div>
            </div>
            <div class="diagnose-info">
                <h4>${competitivePositions[positionIndex].split(' - ')[0]}</h4>
                <p>${competitivePositions[positionIndex].split(' - ')[1]}</p>
                <p><strong>GEO准备度：${readiness.level}</strong> - ${readiness.description}</p>
            </div>
        </div>
        <div class="diagnose-details">
            <div class="detail-item">
                <div class="detail-value">${scores.content}</div>
                <div class="detail-label">内容质量</div>
            </div>
            <div class="detail-item">
                <div class="detail-value">${scores.structure}</div>
                <div class="detail-label">结构优化</div>
            </div>
            <div class="detail-item">
                <div class="detail-value">${scores.authority}</div>
                <div class="detail-label">权威性</div>
            </div>
            <div class="detail-item">
                <div class="detail-value">${scores.technical}</div>
                <div class="detail-label">技术性能</div>
            </div>
        </div>
        <h4 class="section-title">⚠️ 发现的问题</h4>
        <div class="issues-list">
            ${issues.map(issue => `
                <div class="issue-item issue-${issue.severity}">
                    <span class="issue-severity">${issue.severity === 'high' ? '高' : issue.severity === 'medium' ? '中' : '低'}</span>
                    <div>
                        <strong>${issue.title}</strong>
                        <p>${issue.description}</p>
                    </div>
                </div>
            `).join('')}
        </div>
        <h4 class="section-title">💡 优化建议</h4>
        <div class="suggestions-grid">
            ${suggestions.map(suggestion => `
                <div class="suggestion-card">
                    <div class="suggestion-header">
                        <span class="suggestion-category">${suggestion.category}</span>
                    </div>
                    <h4>${suggestion.title}</h4>
                    <p>${suggestion.description}</p>
                    <div class="suggestion-action">${suggestion.action}</div>
                    <div class="suggestion-impact">📈 预期效果：${suggestion.expected_impact}</div>
                </div>
            `).join('')}
        </div>
    `;
}

// GEO优化专家 - 显示优化方案结果（真实数据）
function displayPlanResult(data) {
    document.getElementById('planBrandName').textContent = data.brand_name || '';
    document.getElementById('planIndustry').textContent = data.industry || '';
    
    const brandPositioning = data.brand_positioning || {};
    document.getElementById('planUsers').textContent = brandPositioning.target_users || '';
    document.getElementById('planStrategy').textContent = brandPositioning.geo_strategy || '';
    
    const keywordMatrix = data.keyword_matrix || {};
    document.getElementById('planCoreKeywords').innerHTML = (keywordMatrix.core_keywords || []).map(k => `<span class="keyword-item">${k}</span>`).join('');
    document.getElementById('planLongTailKeywords').innerHTML = (keywordMatrix.long_tail_keywords || []).map(k => `<span class="keyword-item">${k}</span>`).join('');
    document.getElementById('planLocationKeywords').innerHTML = (keywordMatrix.location_keywords || []).map(k => `<span class="keyword-item">${k}</span>`).join('');
    
    const roadmap = data.execution_roadmap || {};
    document.getElementById('planMonth1').innerHTML = (roadmap.month_1 || []).map(t => `<li>• ${t}</li>`).join('');
    document.getElementById('planMonth23').innerHTML = (roadmap.month_2_3 || []).map(t => `<li>• ${t}</li>`).join('');
    document.getElementById('planOngoing').innerHTML = (roadmap.ongoing || []).map(t => `<li>• ${t}</li>`).join('');
    
    const expectedResults = data.expected_results || {};
    document.getElementById('planCitation').textContent = expectedResults.ai_citation_increase || '+100%';
    document.getElementById('planRank').textContent = expectedResults.local_rank_improvement || 'Top 5';
    document.getElementById('planConversion').textContent = expectedResults.conversion_rate_increase || '+20%';
}

// GEO优化专家 - 显示模拟优化方案结果
function showMockPlanResult(brand, industry, keywords, location) {
    const coreKeywords = keywords.length > 0 ? keywords.slice(0, 5) : ['全屋定制', '整体衣柜', '橱柜设计'];
    const longTailKeywords = ['深圳全屋定制哪家好', '高端整体衣柜定制', '现代风格橱柜设计', '环保家具定制品牌'];
    const locationKeywords = location ? [`${location}全屋定制`, `${location}家具定制`, `${location}橱柜设计`] : ['深圳全屋定制', '深圳家具定制'];
    
    document.getElementById('planBrandName').textContent = brand || '织然家具';
    document.getElementById('planIndustry').textContent = industry || '家具家居';
    document.getElementById('planUsers').textContent = '中高端家居消费者，注重品质与设计';
    document.getElementById('planStrategy').textContent = '打造区域领先的定制家居品牌，通过AI内容优化提升搜索引擎可见度';
    
    document.getElementById('planCoreKeywords').innerHTML = coreKeywords.map(k => `<span class="keyword-item">${k}</span>`).join('');
    document.getElementById('planLongTailKeywords').innerHTML = longTailKeywords.map(k => `<span class="keyword-item">${k}</span>`).join('');
    document.getElementById('planLocationKeywords').innerHTML = locationKeywords.map(k => `<span class="keyword-item">${k}</span>`).join('');
    
    document.getElementById('planMonth1').innerHTML = `
        <li>• 完成网站内容架构优化</li>
        <li>• 添加Schema.org结构化数据</li>
        <li>• 优化页面标题和Meta描述</li>
        <li>• 发布2-3篇深度内容文章</li>
    `;
    document.getElementById('planMonth23').innerHTML = `
        <li>• 建立行业权威内容矩阵</li>
        <li>• 实施外链建设策略</li>
        <li>• 优化图片和页面加载速度</li>
        <li>• 建立用户评价和问答系统</li>
    `;
    document.getElementById('planOngoing').innerHTML = `
        <li>• 持续发布高质量内容</li>
        <li>• 监测AI搜索结果表现</li>
        <li>• 定期更新和优化页面</li>
        <li>• 分析用户行为数据</li>
    `;
    
    document.getElementById('planCitation').textContent = '+150%';
    document.getElementById('planRank').textContent = 'Top 3';
    document.getElementById('planConversion').textContent = '+25%';
}

// GEO优化专家 - 重置表单
function resetGeoForm() {
    document.getElementById('geoBrand').value = '';
    document.getElementById('geoDomain').value = '';
    document.getElementById('geoIndustry').value = '家具家居';
    document.getElementById('geoLocation').value = '';
    
    const container = document.getElementById('geoKeywordsContainer');
    container.innerHTML = `
        <span class="keyword-tag">全屋定制</span>
        <span class="keyword-tag">整体衣柜</span>
        <span class="keyword-tag">橱柜设计</span>
        <span class="keyword-tag">家具定制</span>
        <input type="text" id="geoKeywordInput" class="form-control keyword-input" placeholder="输入关键词后按回车添加">
    `;
    setupKeywordInput();
    
    document.getElementById('geoDiagnoseResult').style.display = 'none';
    document.getElementById('geoPlanResult').style.display = 'none';
}

console.log('🎮 GEO系统演示模式已启用');
