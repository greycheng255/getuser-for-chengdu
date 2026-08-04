#!/bin/bash
# GEO系统数据库恢复脚本
# 从备份文件恢复PostgreSQL数据库

# 配置
DB_HOST="122.51.51.177"
DB_PORT="15432"
DB_NAME="geo"
DB_USER="geo"
BACKUP_DIR="/home/ubuntu/GEO/geo_system/backups"

# 显示帮助信息
show_help() {
    echo "GEO系统数据库恢复工具"
    echo ""
    echo "用法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  -l, --list          列出所有可用的备份文件"
    echo "  -r, --restore FILE  从指定备份文件恢复"
    echo "  -h, --help          显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  $0 --list"
    echo "  $0 --restore geo_backup_20260528_191817.sql.gz"
}

# 列出备份文件
list_backups() {
    echo "可用的备份文件:"
    echo ""
    ls -lht ${BACKUP_DIR}/*.sql.gz 2>/dev/null | awk '{print $9, $5, $6, $7, $8}' | nl
    echo ""
    echo "使用 --restore 文件名 进行恢复"
}

# 恢复数据库
restore_database() {
    local backup_file=$1
    local full_path="${BACKUP_DIR}/${backup_file}"
    
    # 检查文件是否存在
    if [ ! -f "${full_path}" ]; then
        echo "❌ 备份文件不存在: ${full_path}"
        exit 1
    fi
    
    echo "⚠️  警告: 恢复数据库将覆盖现有数据！"
    echo "备份文件: ${backup_file}"
    read -p "是否继续? (yes/no): " confirm
    
    if [ "$confirm" != "yes" ]; then
        echo "已取消恢复操作"
        exit 0
    fi
    
    # 创建临时目录
    local temp_dir=$(mktemp -d)
    
    # 解压备份文件
    echo "正在解压备份文件..."
    if [[ "${backup_file}" == *.gz ]]; then
        gunzip -c "${full_path}" > "${temp_dir}/restore.sql"
    else
        cp "${full_path}" "${temp_dir}/restore.sql"
    fi
    
    # 恢复数据库
    echo "正在恢复数据库..."
    sudo docker exec -i yunda-pg psql -U ${DB_USER} -d ${DB_NAME} < "${temp_dir}/restore.sql"
    
    if [ $? -eq 0 ]; then
        echo "✅ 数据库恢复成功"
    else
        echo "❌ 数据库恢复失败"
    fi
    
    # 清理临时文件
    rm -rf ${temp_dir}
}

# 主逻辑
case "$1" in
    -l|--list)
        list_backups
        ;;
    -r|--restore)
        if [ -z "$2" ]; then
            echo "❌ 请指定备份文件"
            show_help
            exit 1
        fi
        restore_database "$2"
        ;;
    -h|--help|*)
        show_help
        ;;
esac
