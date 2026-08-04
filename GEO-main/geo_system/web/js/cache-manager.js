/**
 * 缓存管理器
 * 提供本地存储缓存、内存缓存和请求去重功能
 */

class CacheManager {
    constructor(options = {}) {
        this.options = {
            prefix: 'geo_cache_',
            defaultTTL: 5 * 60 * 1000, // 默认5分钟
            maxMemoryCacheSize: 100, // 内存缓存最大条目数
            ...options
        };

        this.memoryCache = new Map();
        this.pendingRequests = new Map();
    }

    // ==================== 本地存储缓存 ====================

    /**
     * 设置本地存储缓存
     */
    setLocal(key, value, ttl = this.options.defaultTTL) {
        const item = {
            value,
            expires: Date.now() + ttl,
            created: Date.now()
        };
        localStorage.setItem(this.options.prefix + key, JSON.stringify(item));
    }

    /**
     * 获取本地存储缓存
     */
    getLocal(key) {
        const item = localStorage.getItem(this.options.prefix + key);
        if (!item) return null;

        try {
            const parsed = JSON.parse(item);
            if (parsed.expires && Date.now() > parsed.expires) {
                localStorage.removeItem(this.options.prefix + key);
                return null;
            }
            return parsed.value;
        } catch (e) {
            localStorage.removeItem(this.options.prefix + key);
            return null;
        }
    }

    /**
     * 删除本地存储缓存
     */
    removeLocal(key) {
        localStorage.removeItem(this.options.prefix + key);
    }

    /**
     * 清空本地存储缓存
     */
    clearLocal() {
        const keys = Object.keys(localStorage);
        keys.forEach(key => {
            if (key.startsWith(this.options.prefix)) {
                localStorage.removeItem(key);
            }
        });
    }

    // ==================== 内存缓存 ====================

    /**
     * 设置内存缓存
     */
    setMemory(key, value, ttl = this.options.defaultTTL) {
        // LRU清理
        if (this.memoryCache.size >= this.options.maxMemoryCacheSize) {
            const firstKey = this.memoryCache.keys().next().value;
            this.memoryCache.delete(firstKey);
        }

        this.memoryCache.set(key, {
            value,
            expires: Date.now() + ttl
        });
    }

    /**
     * 获取内存缓存
     */
    getMemory(key) {
        const item = this.memoryCache.get(key);
        if (!item) return null;

        if (item.expires && Date.now() > item.expires) {
            this.memoryCache.delete(key);
            return null;
        }

        return item.value;
    }

    /**
     * 删除内存缓存
     */
    removeMemory(key) {
        this.memoryCache.delete(key);
    }

    /**
     * 清空内存缓存
     */
    clearMemory() {
        this.memoryCache.clear();
    }

    // ==================== 请求去重 ====================

    /**
     * 执行带缓存的请求
     */
    async fetchWithCache(url, options = {}) {
        const cacheKey = options.cacheKey || url;
        const cacheType = options.cacheType || 'memory'; // 'memory' | 'local' | 'none'
        const ttl = options.ttl || this.options.defaultTTL;

        // 检查缓存
        if (cacheType !== 'none') {
            const cached = cacheType === 'local' 
                ? this.getLocal(cacheKey) 
                : this.getMemory(cacheKey);
            
            if (cached !== null) {
                console.log(`[Cache] Hit: ${cacheKey}`);
                return cached;
            }
        }

        // 检查是否有进行中的相同请求
        if (this.pendingRequests.has(cacheKey)) {
            console.log(`[Cache] Reusing pending request: ${cacheKey}`);
            return this.pendingRequests.get(cacheKey);
        }

        // 发起请求
        const requestPromise = fetch(url, options)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                // 缓存结果
                if (cacheType === 'local') {
                    this.setLocal(cacheKey, data, ttl);
                } else if (cacheType === 'memory') {
                    this.setMemory(cacheKey, data, ttl);
                }
                return data;
            })
            .finally(() => {
                this.pendingRequests.delete(cacheKey);
            });

        this.pendingRequests.set(cacheKey, requestPromise);
        return requestPromise;
    }

    /**
     * 清除特定URL的缓存
     */
    invalidate(url) {
        this.removeMemory(url);
        this.removeLocal(url);
    }

    /**
     * 批量清除缓存
     */
    invalidatePattern(pattern) {
        // 清除内存缓存
        for (const key of this.memoryCache.keys()) {
            if (key.includes(pattern)) {
                this.memoryCache.delete(key);
            }
        }

        // 清除本地存储缓存
        const keys = Object.keys(localStorage);
        keys.forEach(key => {
            if (key.startsWith(this.options.prefix) && key.includes(pattern)) {
                localStorage.removeItem(key);
            }
        });
    }
}


/**
 * 防抖函数
 */
function debounce(func, wait = 300, immediate = false) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            timeout = null;
            if (!immediate) func(...args);
        };
        const callNow = immediate && !timeout;
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
        if (callNow) func(...args);
    };
}


/**
 * 节流函数
 */
function throttle(func, limit = 300) {
    let inThrottle;
    return function executedFunction(...args) {
        if (!inThrottle) {
            func(...args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}


/**
 * 虚拟列表渲染器
 * 用于优化长列表性能
 */
class VirtualList {
    constructor(options) {
        this.options = {
            container: null,
            itemHeight: 50,
            overscan: 5,
            renderItem: null,
            ...options
        };

        this.container = typeof this.options.container === 'string'
            ? document.querySelector(this.options.container)
            : this.options.container;

        this.items = [];
        this.visibleRange = { start: 0, end: 0 };
        this.scrollTop = 0;

        this.init();
    }

    init() {
        this.viewport = document.createElement('div');
        this.viewport.style.position = 'relative';
        this.viewport.style.overflow = 'auto';
        this.viewport.style.height = '100%';

        this.content = document.createElement('div');
        this.content.style.position = 'relative';

        this.viewport.appendChild(this.content);
        this.container.appendChild(this.viewport);

        this.viewport.addEventListener('scroll', throttle(() => {
            this.scrollTop = this.viewport.scrollTop;
            this.updateVisibleItems();
        }, 16));

        window.addEventListener('resize', debounce(() => {
            this.updateVisibleItems();
        }, 100));
    }

    setItems(items) {
        this.items = items;
        this.content.style.height = `${items.length * this.options.itemHeight}px`;
        this.updateVisibleItems();
    }

    updateVisibleItems() {
        const viewportHeight = this.viewport.clientHeight;
        const startIndex = Math.max(0, Math.floor(this.scrollTop / this.options.itemHeight) - this.options.overscan);
        const endIndex = Math.min(
            this.items.length,
            Math.ceil((this.scrollTop + viewportHeight) / this.options.itemHeight) + this.options.overscan
        );

        if (startIndex === this.visibleRange.start && endIndex === this.visibleRange.end) {
            return;
        }

        this.visibleRange = { start: startIndex, end: endIndex };
        this.render();
    }

    render() {
        const fragment = document.createDocumentFragment();

        for (let i = this.visibleRange.start; i < this.visibleRange.end; i++) {
            const item = this.items[i];
            const element = this.options.renderItem(item, i);
            element.style.position = 'absolute';
            element.style.top = `${i * this.options.itemHeight}px`;
            element.style.left = '0';
            element.style.right = '0';
            element.style.height = `${this.options.itemHeight}px`;
            fragment.appendChild(element);
        }

        this.content.innerHTML = '';
        this.content.appendChild(fragment);
    }
}


/**
 * 图片懒加载
 */
function initLazyImages(selector = 'img[data-src]') {
    const imageObserver = new IntersectionObserver((entries, observer) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const img = entry.target;
                img.src = img.dataset.src;
                img.removeAttribute('data-src');
                observer.unobserve(img);
            }
        });
    }, {
        rootMargin: '50px'
    });

    document.querySelectorAll(selector).forEach(img => {
        imageObserver.observe(img);
    });
}


/**
 * 预加载关键资源
 */
function preloadResources(urls) {
    urls.forEach(url => {
        const link = document.createElement('link');
        link.rel = 'preload';
        link.href = url;
        
        if (url.match(/\.(js)$/)) {
            link.as = 'script';
        } else if (url.match(/\.(css)$/)) {
            link.as = 'style';
        } else if (url.match(/\.(jpg|jpeg|png|gif|webp|svg)$/)) {
            link.as = 'image';
        }

        document.head.appendChild(link);
    });
}


// 创建全局缓存管理器实例
const cacheManager = new CacheManager();

// 导出模块
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        CacheManager,
        cacheManager,
        debounce,
        throttle,
        VirtualList,
        initLazyImages,
        preloadResources
    };
}
