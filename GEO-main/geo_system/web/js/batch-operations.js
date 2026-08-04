/**
 * 批量操作组件
 * 提供统一的批量选择、操作功能
 */

class BatchOperations {
    constructor(options) {
        this.options = {
            container: null,           // 容器元素
            itemSelector: '.item',     // 项目选择器
            checkboxSelector: 'input[type="checkbox"]', // 复选框选择器
            onSelectionChange: null,   // 选择变化回调
            onBatchAction: null,       // 批量操作回调
            actions: [],               // 可用操作 [{id, label, icon, confirm}]
            ...options
        };

        this.selectedItems = new Set();
        this.isAllSelected = false;

        this.init();
    }

    init() {
        this.render();
        this.bindEvents();
    }

    render() {
        const container = typeof this.options.container === 'string'
            ? document.querySelector(this.options.container)
            : this.options.container;

        if (!container) return;

        const toolbar = document.createElement('div');
        toolbar.className = 'batch-toolbar';
        toolbar.innerHTML = `
            <div class="batch-toolbar-left">
                <label class="batch-checkbox-all">
                    <input type="checkbox" id="selectAllCheckbox">
                    <span>全选</span>
                </label>
                <span class="batch-selected-count" id="selectedCount">已选择 0 项</span>
            </div>
            <div class="batch-toolbar-right" id="batchActions">
                ${this.options.actions.map(action => `
                    <button class="geo-btn geo-btn-secondary geo-btn-sm batch-action-btn" 
                            data-action="${action.id}"
                            ${action.confirm ? `data-confirm="${action.confirm}"` : ''}>
                        <span>${action.icon || ''}</span>
                        <span>${action.label}</span>
                    </button>
                `).join('')}
            </div>
        `;

        // 插入到容器顶部
        container.insertBefore(toolbar, container.firstChild);

        // 为每个项目添加复选框
        const items = container.querySelectorAll(this.options.itemSelector);
        items.forEach((item, index) => {
            const checkbox = document.createElement('div');
            checkbox.className = 'batch-item-checkbox';
            checkbox.innerHTML = `<input type="checkbox" data-index="${index}" data-id="${item.dataset.id || index}">`;
            item.insertBefore(checkbox, item.firstChild);
            item.classList.add('batch-selectable');
        });

        this.container = container;
        this.updateUI();
    }

    bindEvents() {
        // 全选/取消全选
        const selectAllCheckbox = this.container.querySelector('#selectAllCheckbox');
        if (selectAllCheckbox) {
            selectAllCheckbox.addEventListener('change', (e) => {
                this.toggleSelectAll(e.target.checked);
            });
        }

        // 单个项目选择
        this.container.addEventListener('change', (e) => {
            if (e.target.matches(this.options.checkboxSelector)) {
                const id = e.target.dataset.id;
                if (e.target.checked) {
                    this.selectedItems.add(id);
                } else {
                    this.selectedItems.delete(id);
                }
                this.updateUI();
                this.triggerSelectionChange();
            }
        });

        // 批量操作按钮
        const actionButtons = this.container.querySelectorAll('.batch-action-btn');
        actionButtons.forEach(btn => {
            btn.addEventListener('click', (e) => {
                const action = btn.dataset.action;
                const confirmMsg = btn.dataset.confirm;

                if (this.selectedItems.size === 0) {
                    alert('请先选择项目');
                    return;
                }

                if (confirmMsg && !confirm(confirmMsg)) {
                    return;
                }

                if (this.options.onBatchAction) {
                    this.options.onBatchAction(action, Array.from(this.selectedItems));
                }
            });
        });
    }

    toggleSelectAll(select) {
        const checkboxes = this.container.querySelectorAll(`${this.options.itemSelector} ${this.options.checkboxSelector}`);
        this.selectedItems.clear();

        checkboxes.forEach(checkbox => {
            checkbox.checked = select;
            if (select) {
                this.selectedItems.add(checkbox.dataset.id);
            }
        });

        this.isAllSelected = select;
        this.updateUI();
        this.triggerSelectionChange();
    }

    updateUI() {
        const count = this.selectedItems.size;
        const countEl = this.container.querySelector('#selectedCount');
        if (countEl) {
            countEl.textContent = `已选择 ${count} 项`;
        }

        // 更新全选复选框状态
        const selectAllCheckbox = this.container.querySelector('#selectAllCheckbox');
        if (selectAllCheckbox) {
            const totalItems = this.container.querySelectorAll(`${this.options.itemSelector} ${this.options.checkboxSelector}`).length;
            selectAllCheckbox.checked = count > 0 && count === totalItems;
            selectAllCheckbox.indeterminate = count > 0 && count < totalItems;
        }

        // 更新批量操作按钮状态
        const actionButtons = this.container.querySelectorAll('.batch-action-btn');
        actionButtons.forEach(btn => {
            btn.disabled = count === 0;
            btn.style.opacity = count === 0 ? '0.5' : '1';
        });
    }

    triggerSelectionChange() {
        if (this.options.onSelectionChange) {
            this.options.onSelectionChange(Array.from(this.selectedItems));
        }
    }

    getSelectedItems() {
        return Array.from(this.selectedItems);
    }

    clearSelection() {
        this.selectedItems.clear();
        const checkboxes = this.container.querySelectorAll(this.options.checkboxSelector);
        checkboxes.forEach(checkbox => checkbox.checked = false);
        this.updateUI();
    }

    destroy() {
        const toolbar = this.container.querySelector('.batch-toolbar');
        if (toolbar) {
            toolbar.remove();
        }

        const checkboxes = this.container.querySelectorAll('.batch-item-checkbox');
        checkboxes.forEach(checkbox => checkbox.remove());

        const items = this.container.querySelectorAll('.batch-selectable');
        items.forEach(item => item.classList.remove('batch-selectable'));
    }
}


/**
 * 数据导出工具
 */
class DataExporter {
    static exportToCSV(data, filename, columns) {
        // 构建CSV内容
        const headers = columns.map(col => col.label).join(',');
        const rows = data.map(row => {
            return columns.map(col => {
                const value = col.key.includes('.') 
                    ? col.key.split('.').reduce((obj, key) => obj?.[key], row)
                    : row[col.key];
                return this.escapeCSV(value);
            }).join(',');
        });

        const csv = [headers, ...rows].join('\n');
        this.downloadFile(csv, filename, 'text/csv;charset=utf-8;');
    }

    static exportToJSON(data, filename) {
        const json = JSON.stringify(data, null, 2);
        this.downloadFile(json, filename, 'application/json');
    }

    static exportToExcel(data, filename, columns) {
        // 简单的HTML表格格式，可以被Excel打开
        const html = `
            <html xmlns:o="urn:schemas-microsoft-com:office:office" 
                  xmlns:x="urn:schemas-microsoft-com:office:excel" 
                  xmlns="http://www.w3.org/TR/REC-html40">
            <head>
                <meta charset="utf-8">
                <style>
                    table { border-collapse: collapse; }
                    th, td { border: 1px solid #ccc; padding: 8px; text-align: left; }
                    th { background-color: #f0f0f0; font-weight: bold; }
                </style>
            </head>
            <body>
                <table>
                    <thead>
                        <tr>${columns.map(col => `<th>${col.label}</th>`).join('')}</tr>
                    </thead>
                    <tbody>
                        ${data.map(row => `
                            <tr>${columns.map(col => {
                                const value = col.key.includes('.') 
                                    ? col.key.split('.').reduce((obj, key) => obj?.[key], row)
                                    : row[col.key];
                                return `<td>${value || ''}</td>`;
                            }).join('')}</tr>
                        `).join('')}
                    </tbody>
                </table>
            </body>
            </html>
        `;
        this.downloadFile(html, filename, 'application/vnd.ms-excel');
    }

    static escapeCSV(value) {
        if (value === null || value === undefined) return '';
        const str = String(value);
        if (str.includes(',') || str.includes('"') || str.includes('\n')) {
            return `"${str.replace(/"/g, '""')}"`;
        }
        return str;
    }

    static downloadFile(content, filename, mimeType) {
        const blob = new Blob([content], { type: mimeType });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
    }
}


/**
 * 表格排序功能
 */
class TableSorter {
    constructor(tableElement) {
        this.table = tableElement;
        this.currentSort = { column: null, direction: 'asc' };
        this.init();
    }

    init() {
        const headers = this.table.querySelectorAll('th[data-sortable]');
        headers.forEach(header => {
            header.style.cursor = 'pointer';
            header.addEventListener('click', () => this.sort(header));

            // 添加排序图标
            const icon = document.createElement('span');
            icon.className = 'sort-icon';
            icon.style.marginLeft = '4px';
            icon.innerHTML = '↕️';
            header.appendChild(icon);
        });
    }

    sort(header) {
        const column = header.dataset.sortable;
        const tbody = this.table.querySelector('tbody');
        const rows = Array.from(tbody.querySelectorAll('tr'));

        // 确定排序方向
        if (this.currentSort.column === column) {
            this.currentSort.direction = this.currentSort.direction === 'asc' ? 'desc' : 'asc';
        } else {
            this.currentSort.column = column;
            this.currentSort.direction = 'asc';
        }

        // 更新图标
        this.table.querySelectorAll('.sort-icon').forEach(icon => {
            icon.innerHTML = '↕️';
        });
        const currentIcon = header.querySelector('.sort-icon');
        if (currentIcon) {
            currentIcon.innerHTML = this.currentSort.direction === 'asc' ? '↑' : '↓';
        }

        // 排序行
        const sortedRows = rows.sort((a, b) => {
            const aValue = this.getCellValue(a, column);
            const bValue = this.getCellValue(b, column);

            if (aValue < bValue) return this.currentSort.direction === 'asc' ? -1 : 1;
            if (aValue > bValue) return this.currentSort.direction === 'asc' ? 1 : -1;
            return 0;
        });

        // 重新排列DOM
        sortedRows.forEach(row => tbody.appendChild(row));
    }

    getCellValue(row, column) {
        const cell = row.querySelector(`[data-column="${column}"]`);
        if (!cell) return '';

        const value = cell.dataset.value || cell.textContent;

        // 尝试转换为数字
        const numValue = parseFloat(value);
        if (!isNaN(numValue)) return numValue;

        // 尝试转换为日期
        const dateValue = new Date(value);
        if (!isNaN(dateValue.getTime())) return dateValue;

        return value.toLowerCase();
    }
}


// 导出模块
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { BatchOperations, DataExporter, TableSorter };
}
