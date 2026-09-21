-- 容器首次初始化时执行（挂载到 /docker-entrypoint-initdb.d）。
-- 创建供集成/并发测试使用的独立空库，与开发库物理隔离。
CREATE DATABASE IF NOT EXISTS course_management_test
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_0900_ai_ci;

GRANT ALL PRIVILEGES ON course_management_test.* TO 'cm_app'@'%';
FLUSH PRIVILEGES;
