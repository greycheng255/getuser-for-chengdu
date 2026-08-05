CREATE TABLE IF NOT EXISTS website_diagnosis (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT DEFAULT NULL,
    domain VARCHAR(255) NOT NULL,
    url VARCHAR(500) NOT NULL,
    brand_name VARCHAR(255) DEFAULT '',
    overall_score DECIMAL(5,2) DEFAULT 0,
    content_score DECIMAL(5,2) DEFAULT 0,
    structure_score DECIMAL(5,2) DEFAULT 0,
    authority_score DECIMAL(5,2) DEFAULT 0,
    technical_score DECIMAL(5,2) DEFAULT 0,
    issues_count INT DEFAULT 0,
    issues TEXT,
    suggestions TEXT,
    diagnosis_result TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_domain (domain),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS geo_optimization_plan (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT DEFAULT NULL,
    domain VARCHAR(255) NOT NULL,
    brand_name VARCHAR(255) NOT NULL,
    industry VARCHAR(100) DEFAULT '',
    location VARCHAR(100) DEFAULT '',
    keywords TEXT,
    plan_data TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_domain (domain),
    INDEX idx_brand_name (brand_name),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS keyword_generation (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT DEFAULT NULL,
    brand_name VARCHAR(255) NOT NULL,
    industry VARCHAR(100) DEFAULT '',
    location VARCHAR(100) DEFAULT '',
    generated_keywords TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_brand_name (brand_name),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
