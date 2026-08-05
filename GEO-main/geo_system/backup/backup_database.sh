#!/bin/bash
# GEO系统数据库备份脚本
# 自动备份PostgreSQL数据库

# 配置
DB_HOST="122.51.51.177"
DB_PORT="15432"
DB_NAME="geo"
DB_USER="geo"
BACKUP_DIR="/home/ubuntu/GEO/geo_system/backups"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/geo_backup_${DATE}.sql"
RETENTION_DAYS=30

# 创建备份目录
mkdir -p ${BACKUP_DIR}

# 执行备份
echo "开始备份数据库 ${DB_NAME}..."
sudo docker exec yunda-pg pg_dump -U ${DB_USER} -d ${DB_NAME} > ${BACKUP_FILE}

# 检查备份是否成功
if [ $? -eq 0 ]; then
    echo "✅ 备份成功: ${BACKUP_FILE}"
    
    # 压缩备份文件
    gzip ${BACKUP_FILE}
    echo "✅ 备份文件已压缩: ${BACKUP_FILE}.gz"
    
    # 删除旧备份（保留30天）
    find ${BACKUP_DIR} -name "geo_backup_*.sql.gz" -mtime +${RETENTION_DAYS} -delete
    echo "✅ 已清理 ${RETENTION_DAYS} 天前的旧备份"
    
    # 显示备份文件列表
    echo ""
    echo "当前备份文件:"
    ls -lh ${BACKUP_DIR}/*.sql.gz 2>/dev/null || echo "暂无备份文件"
else
    echo "❌ 备份失败"
    exit 1
fi
